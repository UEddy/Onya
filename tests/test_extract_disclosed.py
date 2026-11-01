"""Focused tests for src/extract_disclosed.py (mocked model client; no live calls)."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import extract_disclosed


def _response(content, prompt=10, completion=5):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt,
                              completion_tokens=completion,
                              total_tokens=prompt + completion))


class FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.script:
            raise AssertionError("mocked client ran out of responses")
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script):
        self.chat = SimpleNamespace(completions=FakeCompletions(script))


DOCUMENT = (
    "For the quarter ended September 30, 2025.\n"
    "The total net leverage ratio was 2.29 to 1.00, "
    "compared to a maximum of 4.00 to 1.00.\n"
    "The interest expense coverage ratio was 10.46 to 1.00, "
    "above the minimum of 3.00 to 1.00.\n"
)

PARSED = {
    "period_end": "2025-09-30",
    "covenants": [
        {"name": "total net leverage ratio",
         "direction": "max",
         "threshold": 4.0,
         "actual": 2.29,
         "in_compliance": True,
         "waiver_or_amendment_note": None,
         "quote": "The total net leverage ratio was 2.29 to 1.00, "
                  "compared to a maximum of 4.00 to 1.00."},
        {"name": "interest expense coverage ratio",
         "direction": "min",
         "threshold": 3.0,
         "actual": 10.46,
         "in_compliance": True,
         "waiver_or_amendment_note": None,
         "quote": "The interest expense coverage ratio was 10.46 to 1.00, "
                  "above the minimum of 3.00 to 1.00."},
    ],
}


class ModelConfig(unittest.TestCase):
    def test_baseten_model_and_params(self):
        self.assertEqual(extract_disclosed.MODEL,
                         "meta-models/muse-spark-open-1026")
        self.assertEqual(extract_disclosed.TEMPERATURE, 0)
        self.assertEqual(extract_disclosed.MAX_TOKENS, 16000)

    def test_make_client_uses_baseten_env(self):
        with (patch.dict("os.environ",
                         {"BASETEN_API_KEY": "k", "BASETEN_BASE_URL": "u"}),
              patch.object(extract_disclosed, "OpenAI") as factory):
            extract_disclosed.make_client()
        factory.assert_called_once_with(api_key="k", base_url="u")

    def test_request_sends_schema_fields(self):
        for field in ("period_end", "covenants", "direction", "threshold",
                      "actual", "in_compliance", "waiver_or_amendment_note",
                      "quote"):
            self.assertIn(field, extract_disclosed.SCHEMA)
        self.assertIn('"max"|"min"', extract_disclosed.SCHEMA)

    def test_instructions_require_verbatim_quotes_and_no_inference(self):
        instructions = extract_disclosed.INSTRUCTIONS
        self.assertIn("verbatim", instructions)
        self.assertIn("Never infer or compute numbers", instructions)
        self.assertIn("null", instructions)

    def test_never_reads_answer_key(self):
        source = Path(extract_disclosed.__file__).read_text(encoding="utf-8")
        code = source.replace(extract_disclosed.__doc__ or "", "", 1)
        self.assertNotIn("answer_key", code)


class BuildContent(unittest.TestCase):
    def test_document_first_instructions_second(self):
        content = extract_disclosed.build_content("DOC")
        self.assertTrue(content.startswith("DOC\n\n---\n\n"))
        self.assertIn(extract_disclosed.INSTRUCTIONS, content)


class ParseResponse(unittest.TestCase):
    def test_valid_json_parsed(self):
        client = FakeClient([_response(json.dumps(PARSED))])
        parsed, raw, _ = extract_disclosed.parse_response(client, "content")
        self.assertEqual(parsed, PARSED)
        self.assertIn("period_end", raw)

    def test_code_fences_stripped(self):
        client = FakeClient([_response("```json\n" + json.dumps(PARSED) + "\n```")])
        parsed, _, _ = extract_disclosed.parse_response(client, "content")
        self.assertEqual(parsed["period_end"], "2025-09-30")

    def test_retry_once_on_invalid_json(self):
        client = FakeClient([_response("not json"),
                             _response(json.dumps(PARSED))])
        parsed, _, _ = extract_disclosed.parse_response(client, "content")
        self.assertEqual(parsed, PARSED)
        self.assertEqual(len(client.chat.completions.requests), 2)

    def test_request_uses_model_params(self):
        client = FakeClient([_response(json.dumps(PARSED))])
        extract_disclosed.parse_response(client, "content")
        kwargs = client.chat.completions.requests[0]
        self.assertEqual(kwargs["model"], "meta-models/muse-spark-open-1026")
        self.assertEqual(kwargs["temperature"], 0)
        self.assertEqual(kwargs["max_tokens"], 16000)


class NumberInSource(unittest.TestCase):
    def test_ratio_digits_found(self):
        source = extract_disclosed.normalize(DOCUMENT)
        for value in (2.29, 4.0, 10.46, 3.0):
            self.assertTrue(extract_disclosed.number_in_source(value, source),
                            f"{value} should be found")

    def test_absent_number_returns_false(self):
        source = extract_disclosed.normalize(DOCUMENT)
        self.assertFalse(extract_disclosed.number_in_source(9.99, source))

    def test_non_numeric_returns_false(self):
        source = extract_disclosed.normalize(DOCUMENT)
        self.assertFalse(extract_disclosed.number_in_source(True, source))
        self.assertFalse(extract_disclosed.number_in_source("2.29", source))


class Verify(unittest.TestCase):
    def test_clean_parse_fully_verified(self):
        verified, total, failures = extract_disclosed.verify(PARSED, DOCUMENT)
        self.assertEqual(failures, [])
        self.assertEqual(verified, total)
        self.assertEqual(total, 6)  # 2 quotes + 4 numbers

    def test_bad_quote_flagged(self):
        bad = json.loads(json.dumps(PARSED))
        bad["covenants"][0]["quote"] = "a ratio nobody disclosed anywhere"
        verified, total, failures = extract_disclosed.verify(bad, DOCUMENT)
        self.assertEqual(total, 6)
        self.assertEqual(verified, 5)
        self.assertEqual(len(failures), 1)
        self.assertIn("FAILED QUOTE", failures[0])

    def test_number_not_in_source_flagged(self):
        bad = json.loads(json.dumps(PARSED))
        bad["covenants"][1]["actual"] = 99.99
        verified, total, failures = extract_disclosed.verify(bad, DOCUMENT)
        self.assertEqual(verified, total - 1)
        self.assertTrue(any("FAILED NUMBER" in f for f in failures))

    def test_null_threshold_and_actual_skipped(self):
        parsed = {"period_end": "2026-03-31",
                  "covenants": [{"name": "total leverage",
                                 "direction": "max",
                                 "threshold": 4.75,
                                 "actual": None,
                                 "in_compliance": False,
                                 "waiver_or_amendment_note": None,
                                 "quote": "not in compliance with total leverage"}]}
        doc = "The company was not in compliance with total leverage of 4.75."
        verified, total, failures = extract_disclosed.verify(parsed, doc)
        self.assertEqual(failures, [])
        self.assertEqual((verified, total), (2, 2))  # quote + threshold only


class FetchDocument(unittest.TestCase):
    def test_filing_url_uses_cached_fetch_and_textify(self):
        case = {"ticker": "TRS",
                "filing_url": "https://www.sec.gov/Archives/edgar/data/842633/x.htm"}
        with tempfile.TemporaryDirectory() as tmp:
            cached = Path(tmp) / "filing.htm"
            cached.write_bytes(b"<html><body><p>ratio 2.29</p></body></html>")
            with patch.object(extract_disclosed, "fetch",
                              return_value=cached) as do_fetch:
                text, label = extract_disclosed.fetch_document(case)
        do_fetch.assert_called_once_with(case["filing_url"],
                                         "backtest_TRS_x.htm")
        self.assertIn("ratio 2.29", text)
        self.assertEqual(label, case["filing_url"])

    def test_local_doc_read_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "release.txt"
            doc.write_text("net leverage 5.0", encoding="utf-8")
            case = {"ticker": "SNBR", "local_doc": "release.txt"}
            with patch.object(extract_disclosed, "PROJECT_ROOT", Path(tmp)):
                text, label = extract_disclosed.fetch_document(case)
        self.assertEqual(text, "net leverage 5.0")
        self.assertEqual(label, "release.txt")


class BuildRepairContent(unittest.TestCase):
    def test_includes_source_and_failed_quote(self):
        bad = json.loads(json.dumps(PARSED))
        bad["covenants"][0]["quote"] = "a ratio nobody disclosed anywhere"
        content = extract_disclosed.build_repair_content(
            DOCUMENT, bad["covenants"][0])
        self.assertIn(DOCUMENT, content)
        self.assertIn("a ratio nobody disclosed anywhere", content)

    def test_asks_for_verbatim_sentence_with_number(self):
        content = extract_disclosed.build_repair_content(
            DOCUMENT, PARSED["covenants"][0])
        self.assertIn("exact verbatim sentence from the document", content)
        self.assertIn("containing that number", content)
        self.assertIn("copy characters exactly", content.lower())
        self.assertIn("2.29", content)
        self.assertIn("4.0", content)


class ParseRepairQuote(unittest.TestCase):
    def test_bare_sentence_returned(self):
        self.assertEqual(
            extract_disclosed.parse_repair_quote("The ratio was 2.29."),
            "The ratio was 2.29.")

    def test_code_fences_stripped(self):
        self.assertEqual(
            extract_disclosed.parse_repair_quote(
                "```\nThe ratio was 2.29.\n```"),
            "The ratio was 2.29.")

    def test_json_quote_accepted(self):
        self.assertEqual(
            extract_disclosed.parse_repair_quote(
                json.dumps({"quote": "The ratio was 2.29."})),
            "The ratio was 2.29.")

    def test_empty_response_returns_empty(self):
        self.assertEqual(extract_disclosed.parse_repair_quote(""), "")
        self.assertEqual(extract_disclosed.parse_repair_quote("```\n```"), "")


class RepairQuotes(unittest.TestCase):
    def test_verified_quotes_need_no_repair(self):
        parsed = json.loads(json.dumps(PARSED))
        client = FakeClient([])
        extract_disclosed.repair_quotes(parsed, DOCUMENT, client)
        self.assertEqual(client.chat.completions.requests, [])
        for entry in parsed["covenants"]:
            self.assertTrue(entry["quote_verified"])
            self.assertFalse(entry["repaired"])

    def test_failed_quote_repaired_and_reverified(self):
        parsed = json.loads(json.dumps(PARSED))
        parsed["covenants"][0]["quote"] = "a ratio nobody disclosed anywhere"
        fixed = PARSED["covenants"][0]["quote"]
        client = FakeClient([_response(fixed)])
        extract_disclosed.repair_quotes(parsed, DOCUMENT, client)
        self.assertEqual(len(client.chat.completions.requests), 1)
        self.assertEqual(parsed["covenants"][0]["quote"], fixed)
        self.assertTrue(parsed["covenants"][0]["quote_verified"])
        self.assertTrue(parsed["covenants"][0]["repaired"])
        self.assertTrue(parsed["covenants"][1]["quote_verified"])
        self.assertFalse(parsed["covenants"][1]["repaired"])

    def test_failed_repair_marks_unverified_with_one_attempt(self):
        parsed = json.loads(json.dumps(PARSED))
        parsed["covenants"][0]["quote"] = "a ratio nobody disclosed anywhere"
        client = FakeClient([_response("still not in the document")])
        extract_disclosed.repair_quotes(parsed, DOCUMENT, client)
        self.assertEqual(len(client.chat.completions.requests), 1)
        self.assertFalse(parsed["covenants"][0]["quote_verified"])
        self.assertTrue(parsed["covenants"][0]["repaired"])

    def test_one_attempt_per_item_for_two_failures(self):
        parsed = json.loads(json.dumps(PARSED))
        parsed["covenants"][0]["quote"] = "nowhere sentence one"
        parsed["covenants"][1]["quote"] = "nowhere sentence two"
        client = FakeClient([_response("still nowhere one"),
                             _response("still nowhere two")])
        extract_disclosed.repair_quotes(parsed, DOCUMENT, client)
        self.assertEqual(len(client.chat.completions.requests), 2)
        for entry in parsed["covenants"]:
            self.assertFalse(entry["quote_verified"])
            self.assertTrue(entry["repaired"])

    def test_repair_request_uses_model_params(self):
        parsed = json.loads(json.dumps(PARSED))
        parsed["covenants"][0]["quote"] = "nowhere"
        client = FakeClient([_response(PARSED["covenants"][0]["quote"])])
        extract_disclosed.repair_quotes(parsed, DOCUMENT, client)
        kwargs = client.chat.completions.requests[0]
        self.assertEqual(kwargs["model"], "meta-models/muse-spark-open-1026")
        self.assertEqual(kwargs["temperature"], 0)


class ExtractOne(unittest.TestCase):
    def test_saves_json_and_raw_with_mocked_model(self):
        case = {"ticker": "TRS", "filing_url": "https://example.invalid/f.htm"}
        client = FakeClient([_response(json.dumps(PARSED))])
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(extract_disclosed, "fetch_document",
                               return_value=(DOCUMENT, "src")),
                  redirect_stdout(io.StringIO())):
                parsed, verified, total, failures = extract_disclosed.extract_one(
                    case, client, backtest_dir=tmp)
            saved = json.loads((Path(tmp) / "disclosed_TRS.json").read_text())
            raw = (Path(tmp) / "disclosed_TRS_raw.txt").read_text()
        expected = json.loads(json.dumps(PARSED))
        for entry in expected["covenants"]:
            entry["quote_verified"] = True
            entry["repaired"] = False
        self.assertEqual(parsed, expected)
        self.assertEqual(saved, expected)
        self.assertIn("period_end", raw)
        self.assertEqual(failures, [])
        self.assertEqual(verified, total)
        self.assertEqual(len(client.chat.completions.requests), 1)

    def test_extract_one_repairs_failed_quote(self):
        bad = json.loads(json.dumps(PARSED))
        bad["covenants"][0]["quote"] = "a ratio nobody disclosed anywhere"
        fixed = PARSED["covenants"][0]["quote"]
        case = {"ticker": "TRS", "filing_url": "https://example.invalid/f.htm"}
        client = FakeClient([_response(json.dumps(bad)), _response(fixed)])
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(extract_disclosed, "fetch_document",
                               return_value=(DOCUMENT, "src")),
                  redirect_stdout(io.StringIO())):
                parsed, verified, total, failures = extract_disclosed.extract_one(
                    case, client, backtest_dir=tmp)
            saved = json.loads((Path(tmp) / "disclosed_TRS.json").read_text())
        self.assertEqual(len(client.chat.completions.requests), 2)
        self.assertEqual(parsed["covenants"][0]["quote"], fixed)
        self.assertTrue(parsed["covenants"][0]["quote_verified"])
        self.assertTrue(parsed["covenants"][0]["repaired"])
        self.assertFalse(parsed["covenants"][1]["repaired"])
        self.assertEqual(saved, parsed)
        self.assertEqual(failures, [])
        self.assertEqual(verified, total)


class Main(unittest.TestCase):
    def test_unknown_ticker_exits_2(self):
        companies = [{"ticker": "TRS"}]
        with (patch.object(extract_disclosed, "load_companies",
                           return_value=companies),
              redirect_stdout(io.StringIO()),
              patch("sys.stderr", io.StringIO())):
            with self.assertRaises(SystemExit) as ctx:
                extract_disclosed.main(["extract_disclosed.py", "NOPE"])
        self.assertEqual(ctx.exception.code, 2)

    def test_ticker_filter_selects_cases(self):
        companies = [{"ticker": "TRS"}, {"ticker": "AIN"}]
        seen = []
        with (patch.object(extract_disclosed, "load_companies",
                           return_value=companies),
              patch.object(extract_disclosed, "make_client",
                           return_value=FakeClient([])),
              patch.object(extract_disclosed, "extract_one",
                           side_effect=lambda case, client: seen.append(case["ticker"]))):
            extract_disclosed.main(["extract_disclosed.py", "ain"])
        self.assertEqual(seen, ["AIN"])


if __name__ == "__main__":
    unittest.main()
