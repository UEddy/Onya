"""Tests for private mode (src/private_compare.py, POST /private/compare)."""

import base64
import io
import json
import logging
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import private_compare  # noqa: E402

TOKEN = "test-token-123"
MARKER = "MarkerXyZ-private-92741"


def _pdf_bytes(sentence):
    stream = (b"BT /F1 12 Tf 72 720 Td (" + sentence.encode("latin-1")
              + b") Tj ET")
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
         b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>"),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        b"<</Length %d>>stream\n" % len(stream) + stream
        + b"\nendstream",
    ]
    out = [b"%PDF-1.4\n"]
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(sum(len(part) for part in out))
        out.append(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref_pos = sum(len(part) for part in out)
    out.append(b"xref\n0 %d\n" % (len(objects) + 1))
    out.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.append(b"%010d 00000 n \n" % offset)
    out.append(b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n"
               % (len(objects) + 1, xref_pos))
    return b"".join(out)


def _encrypted_pdf_bytes():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    writer.encrypt("pw")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _fake_client(payload, tokens=321):
    completion = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=300,
                              completion_tokens=21,
                              total_tokens=tokens))
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: completion)))


EXTRACTION = {
    "covenants": [
        {"name": "Net Leverage Ratio", "direction": "max",
         "threshold": 4.75, "actual": 5.06,
         "quote": "Net Leverage Ratio 5.06 to 1.00."},
        {"name": "Interest Coverage Ratio", "direction": "min",
         "threshold": 2.1, "actual": 1.7,
         "quote": "a sentence that is not in the document"},
    ],
    "components": [
        {"name": "Consolidated EBITDA", "value": 87230000,
         "quote": "Consolidated EBITDA of $87,230,000"},
    ],
}

DOCUMENT = ("Net Leverage Ratio 5.06 to 1.00. "
            "Consolidated EBITDA of $87,230,000 includes savings. "
            + MARKER)


class FileValidation(unittest.TestCase):
    def test_pdf_sniff_and_extract(self):
        data = _pdf_bytes("Net Leverage Ratio 5.06 to 1.00.")
        self.assertEqual(private_compare.sniff_kind(data), "pdf")
        self.assertIn("Net Leverage Ratio 5.06",
                      private_compare.extract_pdf_text(data))

    def test_text_sniff(self):
        self.assertEqual(private_compare.sniff_kind(b"plain words"),
                         "text")

    def test_unknown_sniff(self):
        self.assertEqual(private_compare.sniff_kind(b"\x00\x01\x02"),
                         "unknown")
        self.assertEqual(private_compare.sniff_kind(b"   "), "unknown")

    def test_encrypted_pdf_rejected(self):
        with self.assertRaises(private_compare.PrivateInputError) as ctx:
            private_compare.prepare_document(
                file_b64=base64.b64encode(_encrypted_pdf_bytes()).decode(),
                filename="cert.pdf")
        self.assertIn("encrypted", str(ctx.exception))

    def test_malformed_pdf_rejected(self):
        with self.assertRaises(private_compare.PrivateInputError):
            private_compare.prepare_document(
                file_b64=base64.b64encode(b"%PDF-1.4 broken").decode(),
                filename="cert.pdf")

    def test_size_cap_content_free(self):
        big = "x" * (private_compare.MAX_UPLOAD_BYTES + 1)
        with self.assertRaises(private_compare.PrivateInputError) as ctx:
            private_compare.prepare_document(text=MARKER + big)
        self.assertNotIn(MARKER, str(ctx.exception))
        self.assertIn("bytes", str(ctx.exception))

    def test_both_and_neither_rejected(self):
        with self.assertRaises(private_compare.PrivateInputError):
            private_compare.prepare_document(text="a", file_b64="eA==")
        with self.assertRaises(private_compare.PrivateInputError):
            private_compare.prepare_document()

    def test_bad_base64_rejected(self):
        with self.assertRaises(private_compare.PrivateInputError):
            private_compare.prepare_document(file_b64="!!!not-base64!!!")


class QuoteVerification(unittest.TestCase):
    def test_verified_flags(self):
        figures, tokens = private_compare.extract_certificate_figures(
            DOCUMENT, _fake_client(EXTRACTION))
        self.assertEqual(tokens, 321)
        by_name = {c["name"]: c for c in figures["covenants"]}
        self.assertTrue(by_name["Net Leverage Ratio"]["verified"])
        self.assertFalse(by_name["Interest Coverage Ratio"]["verified"])
        self.assertTrue(figures["components"][0]["verified"])

    def test_unusable_model_output_rejected(self):
        bad = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(
                        message=SimpleNamespace(content="not json"))],
                    usage=None))))
        with self.assertRaises(private_compare.PrivateInputError):
            private_compare.extract_certificate_figures(DOCUMENT, bad)


class ComparisonMath(unittest.TestCase):
    def test_gap_rows_and_flags(self):
        figures = {"covenants": [
            {"name": "Net Leverage Ratio", "direction": "max",
             "threshold": 4.75, "actual": 5.06, "quote": "q",
             "verified": True},
            {"name": "Interest Coverage Ratio", "direction": "min",
             "threshold": 2.1, "actual": 1.7, "quote": "q",
             "verified": True}],
            "components": [
                {"name": "Consolidated EBITDA", "value": 87230000,
                 "quote": "q", "verified": True}]}
        out = private_compare.compare_with_onya(
            "SNBR", "2026-04-04", figures)
        rows = {r["name"]: r for r in out["rows"]}
        self.assertEqual(rows["Net Leverage Ratio"]["onya"], 6.58)
        self.assertEqual(rows["Net Leverage Ratio"]["certificate"], 5.06)
        self.assertAlmostEqual(
            rows["Net Leverage Ratio"]["difference"], -1.52)
        self.assertTrue(any("cap" in f for f in out["flags"]))
        self.assertTrue(any("administrative agent approval" in f
                            for f in out["flags"]))
        self.assertTrue(out["summary"])

    def test_unsupported_company(self):
        with self.assertRaises(private_compare.PrivateInputError):
            private_compare.compare_with_onya(
                "ACME", "2026-04-04", {"covenants": []})

    def test_cert_ratio_against_limit_flag(self):
        import edgar

        def dead(*args, **kwargs):
            raise AssertionError("network call attempted")

        figures = {"covenants": [
            {"name": "Net Leverage Ratio", "direction": "max",
             "threshold": 4.75, "actual": 5.06, "quote": "q",
             "verified": True},
            {"name": "Interest Coverage Ratio", "direction": "min",
             "threshold": 2.1, "actual": 1.7, "quote": "q",
             "verified": True}],
            "components": []}
        with patch.object(edgar.requests, "get", side_effect=dead), \
             patch.object(edgar.requests, "post", side_effect=dead):
            out = private_compare.compare_with_onya(
                "SNBR", "2026-04-04", figures)
        self.assertIn(
            "The certificate's net leverage of 5.06x is still above "
            "the 4.75x limit. Its compliance statement relies on the "
            "forbearance, not the ratio.",
            out["flags"])
        self.assertIn(
            "The certificate's interest coverage of 1.70x is still "
            "below the 2.10x limit. Its compliance statement relies "
            "on the forbearance, not the ratio.",
            out["flags"])

    def test_no_flag_when_certificate_passes(self):
        figures = {"covenants": [
            {"name": "Net Leverage Ratio", "direction": "max",
             "threshold": 4.75, "actual": 4.0, "quote": "q",
             "verified": True}],
            "components": []}
        out = private_compare.compare_with_onya(
            "SNBR", "2026-04-04", figures)
        self.assertFalse([f for f in out["flags"]
                          if "certificate's net leverage" in f])


class NoPersistence(unittest.TestCase):
    def _snapshot(self):
        return {p for p in (PROJECT_ROOT / "data").rglob("*")}

    def test_run_leaves_no_files_logs_or_traces(self):
        before = self._snapshot()
        with self.assertLogs("onya.private", level="INFO") as logs:
            result, tokens, _timings = private_compare.run_compare(
                "SNBR", "2026-04-04", text=DOCUMENT,
                client=_fake_client(EXTRACTION))
        self.assertEqual(self._snapshot(), before)
        self.assertNotIn(MARKER, "\n".join(logs.output))
        self.assertIn("Net Leverage Ratio", result["rows"][0]["name"])
        self.assertEqual(tokens, 321)


class Endpoint(unittest.TestCase):
    def setUp(self):
        self._old_token = os.environ.get("ONYA_DEMO_TOKEN")
        os.environ["ONYA_DEMO_TOKEN"] = TOKEN
        api._reset_state()
        self.client = TestClient(api.app)

    def tearDown(self):
        if self._old_token is None:
            os.environ.pop("ONYA_DEMO_TOKEN", None)
        else:
            os.environ["ONYA_DEMO_TOKEN"] = TOKEN
        api._reset_state()

    def _env_without_baseten(self):
        env = dict(os.environ)
        env.pop("BASETEN_API_KEY", None)
        env.pop("BASETEN_BASE_URL", None)
        env.pop("ONYA_PRIVATE_REPLAY", None)
        return env

    def test_503_without_baseten_key(self):
        with patch.dict(os.environ, self._env_without_baseten(),
                        clear=True):
            os.environ["ONYA_DEMO_TOKEN"] = TOKEN
            r = self.client.post(
                "/private/compare",
                json={"ticker": "SNBR", "period_end": "2026-04-04",
                      "text": "words"},
                headers={"X-Onya-Token": TOKEN})
        self.assertEqual(r.status_code, 503)
        self.assertIn("unavailable", r.json()["detail"])

    def test_replay_stream_returns_result(self):
        figures = {"covenants": [
            {"name": "Net Leverage Ratio", "direction": "max",
             "threshold": 4.75, "actual": 5.06, "quote": "q",
             "verified": True}],
            "components": []}
        env = self._env_without_baseten()
        env["ONYA_PRIVATE_REPLAY"] = "1"
        with patch.dict(os.environ, env, clear=True):
            os.environ["ONYA_DEMO_TOKEN"] = TOKEN
            with patch.object(api, "_private_replay_figures",
                              return_value={"figures": figures}):
                r = self.client.post(
                    "/private/compare",
                    json={"ticker": "SNBR",
                          "period_end": "2026-04-04",
                          "text": "words"},
                    headers={"X-Onya-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        events = [json.loads(line) for line in r.text.splitlines()
                  if line.strip()]
        kinds = [e.get("type") for e in events]
        self.assertIn("progress", kinds)
        final = next(e for e in events
                     if e.get("type") == "private_result")
        row = final["comparison"]["rows"][0]
        self.assertEqual(row["certificate"], 5.06)
        self.assertEqual(row["onya"], 6.58)

    def test_sample_endpoint(self):
        r = self.client.get("/private/sample",
                            headers={"X-Onya-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["text"].startswith(
            "ILLUSTRATIVE SAMPLE"))

    def test_validation_errors(self):
        env = self._env_without_baseten()
        env["ONYA_PRIVATE_REPLAY"] = "1"
        with patch.dict(os.environ, env, clear=True):
            os.environ["ONYA_DEMO_TOKEN"] = TOKEN
            r = self.client.post(
                "/private/compare",
                json={"ticker": "SNBR", "period_end": "May"},
                headers={"X-Onya-Token": TOKEN})
            self.assertEqual(r.status_code, 422)
            r = self.client.post(
                "/private/compare",
                json={"ticker": "SNBR", "period_end": "2026-04-04"},
                headers={"X-Onya-Token": TOKEN})
            self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()
