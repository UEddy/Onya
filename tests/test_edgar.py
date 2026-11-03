"""Focused regression tests: edgar.main continues past failures; fetch retries."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import requests

import edgar


def _http_error(status):
    resp = SimpleNamespace(status_code=status)
    return requests.HTTPError(f"GET failed with status {status}", response=resp)


class MainContinuesOnFailure(unittest.TestCase):
    def test_failure_prints_filename_and_status_then_continues(self):
        files = [
            ("http://example.invalid/a", "a.htm"),
            ("http://example.invalid/b", "b.htm"),
            ("http://example.invalid/c", "c.htm"),
        ]
        calls = []

        def fake_fetch(url, filename):
            calls.append(filename)
            if filename == "b.htm":
                raise _http_error(404)
            return Path(__file__)  # existing file so stat() works

        with (
            patch.object(edgar, "FILES", files),
            patch.object(edgar, "fetch", side_effect=fake_fetch),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                edgar.main()
        out = buf.getvalue()

        self.assertEqual(calls, ["a.htm", "b.htm", "c.htm"])  # kept going past b.htm
        self.assertIn("b.htm", out)
        self.assertIn("404", out)
        self.assertIn("2 succeeded, 1 failed", out)


class FetchRetry(unittest.TestCase):
    def test_connection_error_retries_3_times_then_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(edgar, "RAW_DIR", Path(tmp)),
                  patch.object(edgar.requests, "get",
                               side_effect=requests.ConnectionError("dns fail")),
                  patch.object(edgar.time, "sleep") as sleep):
                with self.assertRaises(requests.ConnectionError):
                    edgar.fetch("http://example.invalid/a", "a.htm")
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(waits, [5, 15, 30])

    def test_recovers_after_transient_failures(self):
        ok = SimpleNamespace(status_code=200, content=b"data")
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(edgar, "RAW_DIR", Path(tmp)),
                  patch.object(
                      edgar.requests, "get",
                      side_effect=[requests.ConnectionError("down"),
                                    requests.ConnectionError("down"), ok]),
                  patch.object(edgar.time, "sleep") as sleep):
                dest = edgar.fetch("http://example.invalid/a", "a.htm")
            self.assertEqual(dest, Path(tmp) / "a.htm")
            self.assertEqual((Path(tmp) / "a.htm").read_bytes(), b"data")
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(waits, [5, 15, 0.5])

    def test_http_error_raises_without_retry(self):
        bad = SimpleNamespace(status_code=404, content=b"")
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(edgar, "RAW_DIR", Path(tmp)),
                  patch.object(edgar.requests, "get",
                               return_value=bad) as get,
                  patch.object(edgar.time, "sleep") as sleep):
                with self.assertRaises(requests.HTTPError):
                    edgar.fetch("http://example.invalid/a", "a.htm")
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs.get("timeout"), (10, 60))
        sleep.assert_not_called()

    def test_cached_file_returns_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.htm"
            dest.write_bytes(b"cached")
            with patch.object(edgar, "RAW_DIR", Path(tmp)), patch.object(
                    edgar.requests, "get",
                    side_effect=AssertionError("no network")) as get:
                self.assertEqual(
                    edgar.fetch("http://example.invalid/a", "a.htm"), dest)
        get.assert_not_called()


EXHIBIT_INDEX_FIXTURE = """
EXHIBIT INDEX

10.2

Second Amended and Restated Credit Agreement, dated as of July 28, 2017,
among AMC Networks and its subsidiary, as borrowers (incorporated by
reference to Exhibit 10.1 to the Company's Current Report on Form 8-K
filed on July 28, 2017).

10.5

Amendment No. 3, dated as of April 9, 2024, to the Second Amended and
Restated Credit Agreement (incorporated by reference to Exhibit 10.1 to
the Company's Current Report on Form 8-K filed on April 10, 2024).

10.6

Employment Agreement, dated August 4, 2022, by and between AMC Networks
Inc. and Patrick O'Connell (incorporated by reference to Exhibit 10.2
to the Company's Quarterly Report on Form 10-Q for the quarter ended
September 30, 2022).
"""


class IncorporatedReferences(unittest.TestCase):
    def test_credit_entries_parsed_with_pointers(self):
        entries = edgar.exhibit_index_entries(EXHIBIT_INDEX_FIXTURE)
        by_number = {e["number"]: e for e in entries}
        self.assertEqual(set(by_number), {"10.2", "10.5"})
        self.assertEqual(by_number["10.2"]["ref_form"], "8-K")
        self.assertEqual(by_number["10.2"]["ref_date"], "2017-07-28")
        self.assertEqual(by_number["10.2"]["ref_exhibit"], "10.1")
        self.assertEqual(by_number["10.5"]["ref_date"], "2024-04-10")
        self.assertIn("Credit Agreement", by_number["10.2"]["description"])

    def test_non_credit_entries_skipped(self):
        entries = edgar.exhibit_index_entries(
            "EXHIBIT INDEX\n\n10.7\n\nEmployment Agreement with an officer.\n")
        self.assertEqual(entries, [])

    def test_parenthesized_numbers_and_unicode_dashes(self):
        fixture = (
            "EXHIBIT INDEX\n\n(4.7)\nAmendment No. 10, dated as of "
            "August\u00a020, 2025, to Second Amended and Restated Credit "
            "Agreement (incorporated by reference to Exhibit\u00a04.1 to "
            "the Company\u2019s Current Report on Form 8\u2011K dated "
            "August\u00a020, 2025 and filed on August\u00a025, 2025).\n")
        entries = edgar.exhibit_index_entries(fixture)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["number"], "4.7")
        self.assertEqual(entries[0]["ref_exhibit"], "4.1")
        self.assertEqual(entries[0]["ref_form"], "8-K")
        self.assertEqual(entries[0]["ref_date"], "2025-08-25")

    def test_filing_found_by_form_and_date(self):
        recent = {"form": ["8-K", "10-Q"], "filingDate": ["2024-04-10", "2024-05-01"],
                  "accessionNumber": ["0001-24-000010", "0001-24-000020"]}
        self.assertEqual(
            edgar.find_filing_accession(recent, "8-K", "2024-04-10"),
            "0001-24-000010")
        self.assertIsNone(
            edgar.find_filing_accession(recent, "8-K", "2020-01-01"))

    def test_resolver_follows_pointer_to_exhibit(self):
        index_html = (
            "<html><body><table>"
            "<tr><th>Seq</th><th>Description</th><th>Document</th>"
            "<th>Type</th><th>Size</th></tr>"
            "<tr><td>1</td><td>8-K</td><td>a8k.htm</td><td>8-K</td><td>9</td></tr>"
            "<tr><td>2</td><td>EX-10.1</td><td>amend3ex101.htm</td>"
            "<td>EX-10.1</td><td>70000</td></tr>"
            "</table></body></html>")
        exhibit = ("AMENDMENT NO. 3 TO SECOND AMENDED AND RESTATED CREDIT "
                   "AGREEMENT. Consolidated EBITDA means net earnings. "
                   "Section 7.26 Financial Covenant. Leverage Ratio shall "
                   "not exceed 4.50 to 1.00. " + "x" * 61000)
        recent = {"form": ["10-K", "8-K"],
                  "filingDate": ["2025-02-14", "2024-04-10"],
                  "accessionNumber": ["0001-25-000009", "0001-24-000010"]}
        main_docs = {"0001-25-000009": EXHIBIT_INDEX_FIXTURE}
        store = {}
        tmp_holder = {}

        def fake_fetch(url, filename):
            store[filename] = url
            path = Path(tmp_holder["dir"]) / filename
            if "index" in filename:
                path.write_text(index_html, encoding="utf-8")
            else:
                path.write_text(exhibit, encoding="utf-8")
            return path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_holder["dir"] = tmp
            with patch.object(edgar, "fetch", side_effect=fake_fetch), \
                 patch.object(edgar, "get_cik",
                              return_value="0000000000"):
                found = edgar.resolve_incorporated_agreement(
                    "TST", "2025-11-14",
                    recent=recent, main_docs=main_docs)
        self.assertEqual(len(found), 2)
        by_date = {c["filingDate"]: c for c in found}
        pointed = by_date["2024-04-10"]
        self.assertTrue(pointed["url"].endswith("amend3ex101.htm"))
        self.assertTrue(pointed["restates_covenants"])
        direct = by_date["2025-02-14"]
        self.assertTrue(direct["url"].endswith("amend3ex101.htm"))
        self.assertTrue(any(name.endswith("amend3ex101.htm")
                            for name in store))


class PointerWording(unittest.TestCase):
    def entries(self, reference):
        doc = ("Exhibit Index\n10.1\nCredit Agreement dated June 1, 2020 "
               f"({reference}).\nSignatures\n")
        return edgar.exhibit_index_entries(doc)

    def test_company_name_with_a_period_before_the_form(self):
        found = self.entries(
            "incorporated by reference to Exhibit 10.1 to Acme Inc.'s "
            "Current Report on Form 8-K filed June 2, 2020")
        self.assertEqual(found[0]["ref_form"], "8-K")
        self.assertEqual(found[0]["ref_date"], "2020-06-02")

    def test_filed_with_the_sec_on(self):
        found = self.entries(
            "incorporated herein by reference to Exhibit 4.2 of the Form "
            "10-K/A filed with the SEC on March 3, 2021")
        self.assertEqual(found[0]["ref_exhibit"], "4.2")
        self.assertEqual(found[0]["ref_form"], "10-K/A")
        self.assertEqual(found[0]["ref_date"], "2021-03-03")

    def test_no_filing_date_is_no_pointer(self):
        self.assertEqual(self.entries(
            "incorporated by reference to Exhibit 10.1 to the Form 10-Q for "
            "the quarter ended June 30, 2020"), [])


SCANNED_EXHIBIT = (
    b"<html><body><p>Exhibit 10.12</p>"
    b'<img src="p1.jpg"><img src="p2.jpg"><img src="p3.jpg"></body></html>')


class ImageOnlyExhibits(unittest.TestCase):
    def test_pages_counted_when_no_text_layer(self):
        self.assertEqual(edgar.image_only_pages(SCANNED_EXHIBIT), 3)

    def test_text_exhibit_with_a_logo_is_not_image_only(self):
        doc = b'<html><body><img src="logo.jpg"><p>' + b"word " * 200 + b"</p>"
        self.assertEqual(edgar.image_only_pages(doc), 0)

    def test_no_images_is_not_image_only(self):
        self.assertEqual(edgar.image_only_pages(b"<p>Exhibit 10.1</p>"), 0)

    def _find(self, main_text, doc_type="EX-10.12"):
        filing = {"form": "8-K", "items": "1.01", "filingDate": "2023-11-14",
                  "accessionNumber": "0001493152-23-041322"}
        late = dict(filing, filingDate="2027-01-01",
                    accessionNumber="0001493152-27-000001")

        def write(_url, name):
            path = Path(self.tmp.name) / name
            path.write_bytes(SCANNED_EXHIBIT)
            return path

        docs = [{"type": doc_type, "name": "ex.htm"}]
        with patch.object(edgar, "get_cik", return_value="0001866816"), \
                patch.object(edgar, "list_filings",
                             return_value=[filing, late]), \
                patch.object(edgar, "filing_documents", return_value=docs), \
                patch.object(edgar, "fetch", side_effect=write), \
                patch.object(edgar, "_incorporated_main_text",
                             return_value=main_text):
            return edgar.find_image_only_credit_exhibits(
                "OPTX", as_of="2026-05-15")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_credit_exhibit_found_and_cutoff_applied(self):
        found = self._find("10.8 Form of Award 10.12 Credit Agreement 21.1 Subs")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["filingDate"], "2023-11-14")
        self.assertEqual(found[0]["exhibit"], "EX-10.12")
        self.assertEqual(found[0]["pages"], 3)

    def test_scan_the_filing_does_not_call_a_credit_agreement_is_skipped(self):
        self.assertEqual(self._find(
            "10.12 Employment Letter for the Chief Executive Officer"), [])


if __name__ == "__main__":
    unittest.main()
