"""Discovery tests for edgar.py using mocked SEC JSON/HTML. No live fetches."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import edgar

TICKERS = {
    "0": {"cik_str": 827187, "ticker": "SNBR", "title": "Sleep Number Corp"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}

SUBMISSIONS = {
    "cik": "0000827187",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000827187-26-000035",
                "0000827187-25-000123",
                "0000827187-25-000121",
                "0000827187-25-000050",
                "0000827187-24-000010",
                "0000827187-22-000009",
                "0000827187-25-000099",
                "0000827187-25-000200",
            ],
            "filingDate": [
                "2026-01-15",
                "2025-11-10",
                "2025-09-27",
                "2025-03-01",
                "2023-12-15",
                "2022-05-01",
                "2025-06-01",
                "2025-07-15",
            ],
            "reportDate": [
                "2026-01-10",
                "2025-11-10",
                "2025-09-27",
                "2024-12-31",
                "2023-12-12",
                "2022-01-01",
                "2025-06-01",
                "2025-07-15",
            ],
            "form": ["8-K", "8-K", "10-Q", "10-K", "8-K", "10-K", "4", "8-K"],
            "primaryDocument": [
                "snbr-20260115.htm",
                "snbr-20251110.htm",
                "snbr-20250927.htm",
                "snbr-20250301.htm",
                "snbr-20231215.htm",
                "snbr-20220501.htm",
                "ownership.xml",
                "snbr-20250715.htm",
            ],
            "items": [
                "1.01,9.01",
                "2.03",
                "",
                "",
                "1.01",
                "",
                "",
                "2.02,9.01",
            ],
        }
    },
}

# Realistic sample filing index page (-index.htm) as served by EDGAR.
SAMPLE_INDEX_HTML = """<!DOCTYPE html>
<html>
<head><title>EDGAR Filing Documents for 0000827187-25-000123</title></head>
<body>
<h1>8-K - Current report</h1>
<div class="formGrouping">
<div class="formHeading">Filing Documents</div>
<div class="formContent">
<table class="tableFile" summary="Document Format Files">
<tr><th scope="col">Seq</th><th scope="col">Description</th><th scope="col">Document</th><th scope="col">Type</th><th scope="col">Size</th></tr>
<tr><td scope="row">1</td><td scope="row">Credit Agreement</td><td scope="row"><a href="/Archives/edgar/data/827187/000082718725000123/a.htm">a.htm</a></td><td scope="row">EX-10.1</td><td scope="row">12345</td></tr>
<tr><td scope="row">2</td><td scope="row"></td><td scope="row"><a href="/Archives/edgar/data/827187/000082718725000123/b.htm">b.htm</a></td><td scope="row">8-K</td><td scope="row">23456</td></tr>
</table>
</div>
</div>
</body>
</html>
"""


def _nodash_to_dashed(nodash):
    return f"{nodash[:10]}-{nodash[10:12]}-{nodash[12:]}"


def _index_html(nodash, rows):
    dashed = _nodash_to_dashed(nodash)
    trs = []
    for i, d in enumerate(rows, 1):
        desc = d.get("description", "")
        name = d["name"]
        typ = d["type"]
        trs.append(
            f'<tr><td scope="row">{i}</td><td scope="row">{desc}</td>'
            f'<td scope="row"><a href="/Archives/edgar/data/827187/'
            f'{nodash}/{name}">{name}</a></td>'
            f'<td scope="row">{typ}</td><td scope="row">12345</td></tr>'
        )
    return (
        "<!DOCTYPE html>\n<html>\n"
        f"<head><title>EDGAR Filing Documents for {dashed}</title></head>\n"
        "<body>\n"
        '<table class="tableFile" summary="Document Format Files">\n'
        "<tr><th scope=\"col\">Seq</th><th scope=\"col\">Description</th>"
        "<th scope=\"col\">Document</th><th scope=\"col\">Type</th>"
        "<th scope=\"col\">Size</th></tr>\n"
        + "\n".join(trs)
        + "\n</table>\n</body>\n</html>\n"
    )


# Accession-without-dashes -> exhibit rows rendered into -index.htm HTML.
INDEX_ROWS = {
    "000082718726000035": [
        {
            "name": "ex101-forbearance.htm",
            "type": "EX-10.1",
            "description": "Forbearance Agreement dated January 2026",
        },
        {"name": "snbr-20260115.htm", "type": "8-K", "description": "Current report"},
    ],
    "000082718725000123": [
        {
            "name": "ex101creditagreement.htm",
            "type": "EX-10.1",
            "description": "Second Amended and Restated Credit Agreement",
        },
        {
            "name": "ex991earnings.htm",
            "type": "EX-99.1",
            "description": "Credit Agreement press release",
        },
    ],
    "000082718725000121": [
        {"name": "ex102.htm", "type": "EX-10.2"},
        {
            "name": "ex103-consulting.htm",
            "type": "EX-10.3",
            "description": "Consulting agreement",
        },
        {
            "name": "ex104-lease.htm",
            "type": "EX-10.4",
            "description": "Amendment to Lease",
        },
        {
            "name": "ex105-executive.htm",
            "type": "EX-10.5",
            "description": "Executive agreement amendment",
        },
    ],
    "000082718725000050": [
        {
            "name": "ex101-credit.htm",
            "type": "EX-10.1",
            "description": "Credit Agreement",
        },
    ],
    "000082718724000010": [
        {
            "name": "ex101old.htm",
            "type": "EX-10.1",
            "description": "Amendment No. 1 to Credit Agreement",
        },
    ],
    "000082718722000009": [
        {"name": "ex101.htm", "type": "EX-10.1", "description": "Credit Agreement"},
    ],
}


# Fixture exhibit documents (docname -> HTML). Classification is by text:
# - Credit and Security Agreement amendment (include)
# - lease amendment (exclude)
# - executive agreement amendment (exclude)
# - generically named exhibit whose text is a credit agreement amendment (include)
EXHIBIT_HTML = {
    "ex101-forbearance.htm": """<html><body>
<p>FORBEARANCE AGREEMENT</p>
<p>Dated as of January 10, 2026, by and among Sleep Number Corporation, as Borrower.</p>
<p>This Forbearance Agreement relates to the Credit Agreement dated as of April 26, 2023.</p>
</body></html>""",
    "ex101creditagreement.htm": """<html><body>
<p>THIRTEENTH AMENDMENT TO</p>
<p>CREDIT AND SECURITY AGREEMENT</p>
<p>Dated as of November 10, 2025, amending the Credit Agreement dated April 26, 2023.</p>
</body></html>""",
    "ex102.htm": """<html><body>
<p>FOURTEENTH AMENDMENT TO CREDIT AGREEMENT</p>
<p>This Amendment, dated September 27, 2025, amends the Credit Agreement.</p>
</body></html>""",
    "ex103-consulting.htm": """<html><body>
<p>CONSULTING AGREEMENT</p>
<p>This Consulting Agreement is entered into as of June 1, 2025.</p>
<p>Nothing herein amends the Credit Agreement.</p>
</body></html>""",
    "ex104-lease.htm": """<html><body>
<p>SECOND AMENDMENT TO LEASE AGREEMENT</p>
<p>This Amendment to Lease dated March 3, 2025, covers the premises at 100 Main Street.</p>
</body></html>""",
    "ex105-executive.htm": """<html><body>
<p>AMENDMENT TO EXECUTIVE EMPLOYMENT AGREEMENT</p>
<p>This Amendment, dated August 1, 2025, is between the Company and the Executive.</p>
</body></html>""",
    "ex101-credit.htm": """<html><body>
<p>SECOND AMENDED AND RESTATED CREDIT AGREEMENT</p>
<p>Dated as of March 1, 2025.</p>
</body></html>""",
    "ex101old.htm": """<html><body>
<p><s>This Lease Agreement dated January 1, 2020 is superseded.</s></p>
<p>AMENDMENT NO. 1 TO CREDIT AGREEMENT</p>
<p>Dated as of December 12, 2023.</p>
</body></html>""",
}


class FakeFetch:
    """Stand-in for edgar.fetch serving mocked JSON/HTML; fails on unknown URLs."""

    def __init__(self, tmpdir):
        self.tmpdir = Path(tmpdir)
        self.calls = []
        self.routes = []

    def add(self, url_substring, payload):
        self.routes.append((url_substring, payload))
        return self

    def __call__(self, url, filename):
        self.calls.append((url, filename))
        for key, payload in self.routes:
            if key in url:
                dest = self.tmpdir / filename
                if isinstance(payload, str):
                    dest.write_text(payload)
                else:
                    dest.write_text(json.dumps(payload))
                return dest
        raise AssertionError(f"unexpected URL in test: {url}")


class DiscoverTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fetch = FakeFetch(self._tmp.name)
        p1 = patch.object(edgar, "fetch", side_effect=self.fetch)
        p1.start()
        self.addCleanup(p1.stop)
        p2 = patch.object(
            edgar.requests,
            "get",
            side_effect=AssertionError("live network disabled in tests"),
        )
        p2.start()
        self.addCleanup(p2.stop)


class GetCik(DiscoverTestBase):
    def test_padded_and_case_insensitive(self):
        self.fetch.add("company_tickers.json", TICKERS)
        self.assertEqual(edgar.get_cik("snbr"), "0000827187")
        self.assertEqual(edgar.get_cik("AAPL"), "0000320193")
        url, filename = self.fetch.calls[0]
        self.assertEqual(url, "https://www.sec.gov/files/company_tickers.json")
        self.assertEqual(filename, "company_tickers.json")

    def test_unknown_ticker_raises(self):
        self.fetch.add("company_tickers.json", TICKERS)
        with self.assertRaises(ValueError):
            edgar.get_cik("NOPE")

    def test_unknown_ticker_mentions_delisted_and_cik(self):
        self.fetch.add("company_tickers.json", TICKERS)
        with self.assertRaises(ValueError) as ctx:
            edgar.get_cik("NOPE")
        msg = str(ctx.exception).lower()
        self.assertIn("delist", msg)
        self.assertIn("cik", msg)

    def test_numeric_cik_skips_lookup(self):
        # No tickers route: must not fetch.
        self.assertEqual(edgar.get_cik("827187"), "0000827187")
        self.assertEqual(edgar.get_cik("0000827187"), "0000827187")
        self.assertEqual(edgar.get_cik(827187), "0000827187")
        self.assertEqual(edgar.get_cik("  827187  "), "0000827187")
        self.assertEqual(self.fetch.calls, [])


class ListFilings(DiscoverTestBase):
    def test_default_form_and_since_filters(self):
        self.fetch.add("submissions/CIK", SUBMISSIONS)
        rows = edgar.list_filings("0000827187")
        self.assertEqual(
            [r["accessionNumber"] for r in rows],
            [
                "0000827187-26-000035",
                "0000827187-25-000123",
                "0000827187-25-000121",
                "0000827187-25-000050",
                "0000827187-25-000200",
            ],
        )
        self.assertEqual(
            set(rows[0]),
            {
                "form",
                "filingDate",
                "accessionNumber",
                "primaryDocument",
                "reportDate",
                "items",
            },
        )
        self.assertEqual(rows[0]["primaryDocument"], "snbr-20260115.htm")
        self.assertEqual(rows[0]["reportDate"], "2026-01-10")
        self.assertEqual(rows[0]["items"], "1.01,9.01")
        self.assertEqual(rows[2]["items"], "")

    def test_cik_padding_and_custom_filters(self):
        self.fetch.add("submissions/CIK", SUBMISSIONS)
        rows = edgar.list_filings(827187, forms=("10-K",), since="2023-01-01")
        self.assertEqual(
            [(r["form"], r["filingDate"]) for r in rows], [("10-K", "2025-03-01")]
        )
        url, filename = self.fetch.calls[0]
        self.assertIn("CIK0000827187.json", url)
        self.assertIn("0000827187", filename)


class FilingDocuments(DiscoverTestBase):
    def test_items_and_optional_description(self):
        self.fetch.add("-index.htm", SAMPLE_INDEX_HTML)
        docs = edgar.filing_documents("0000827187", "0000827187-25-000123")
        self.assertEqual(
            docs,
            [
                {
                    "name": "a.htm",
                    "type": "EX-10.1",
                    "description": "Credit Agreement",
                },
                {"name": "b.htm", "type": "8-K"},
            ],
        )
        url, filename = self.fetch.calls[0]
        self.assertEqual(
            url,
            "https://www.sec.gov/Archives/edgar/data/827187/000082718725000123/0000827187-25-000123-index.htm",
        )
        self.assertTrue(filename.endswith("_index.htm"))

    def test_accepts_nodash_accession(self):
        self.fetch.add("-index.htm", SAMPLE_INDEX_HTML)
        docs = edgar.filing_documents("827187", "000082718725000123")
        self.assertEqual(len(docs), 2)
        url, _ = self.fetch.calls[0]
        self.assertIn("0000827187-25-000123-index.htm", url)


class FindCreditAgreements(DiscoverTestBase):
    def _route_all(self):
        self.fetch.add("company_tickers.json", TICKERS)
        self.fetch.add("submissions/CIK", SUBMISSIONS)
        # Exhibit routes first: exhibit URLs contain both the accession
        # nodash and the docname, so docname must win over the index route.
        for docname, html in EXHIBIT_HTML.items():
            self.fetch.add(docname, html)
        for nodash, rows in INDEX_ROWS.items():
            self.fetch.add(nodash, _index_html(nodash, rows))
        # No route for 000082718725000200: it must be skipped.

    def _route_all_cik(self):
        self.fetch.add("submissions/CIK", SUBMISSIONS)
        for docname, html in EXHIBIT_HTML.items():
            self.fetch.add(docname, html)
        for nodash, rows in INDEX_ROWS.items():
            self.fetch.add(nodash, _index_html(nodash, rows))

    def _find(self, arg="SNBR"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cands = edgar.find_credit_agreements(arg)
        return cands, buf.getvalue()

    def test_candidates_sorted_newest_first(self):
        self._route_all()
        cands, _ = self._find()
        self.assertEqual(
            [c["filingDate"] for c in cands],
            ["2026-01-15", "2025-11-10", "2025-09-27", "2025-03-01", "2023-12-15"],
        )
        self.assertEqual(
            [c["form"] for c in cands], ["8-K", "8-K", "10-Q", "10-K", "8-K"]
        )
        for cand in cands:
            self.assertEqual(
                set(cand),
                {
                    "url",
                    "filingDate",
                    "form",
                    "description",
                    "title",
                    "is_forbearance",
                    "is_amendment",
                    "is_complete",
                    "char_count",
                    "character_count",
                },
            )

    def test_urls_and_descriptions(self):
        self._route_all()
        cands, _ = self._find()
        self.assertEqual(
            cands[0]["url"],
            "https://www.sec.gov/Archives/edgar/data/827187/000082718726000035/ex101-forbearance.htm",
        )
        self.assertIn("Forbearance", cands[0]["description"])
        # Name-only match falls back to the document name.
        self.assertEqual(cands[2]["description"], "ex102.htm")

    def test_exclusions(self):
        self._route_all()
        cands, _ = self._find()
        urls = " ".join(c["url"] for c in cands)
        self.assertNotIn("ex991earnings", urls)  # EX-99 despite keyword
        self.assertNotIn("ex103-consulting", urls)  # consulting in first 500
        self.assertNotIn("ex104-lease", urls)  # lease amendment
        self.assertNotIn("ex105-executive", urls)  # executive amendment
        self.assertNotIn("snbr-20260115.htm", urls)  # non-exhibit type
        self.assertNotIn("000082718722000009", urls)  # filing before 2023
        self.assertNotIn("000082718725000099", urls)  # Form 4 not swept

    def test_skips_8k_without_101_or_203(self):
        self._route_all()
        cands, _ = self._find()
        urls = " ".join(c["url"] for c in cands)
        self.assertNotIn("000082718725000200", urls)
        fetched = " ".join(u for u, _ in self.fetch.calls)
        self.assertNotIn("000082718725000200", fetched)
        # The 5 checked filings were fetched; skipped one was not.
        index_calls = [u for u, _ in self.fetch.calls if "-index.htm" in u]
        self.assertEqual(len(index_calls), 5)

    def test_progress_output(self):
        self._route_all()
        _, out = self._find()
        self.assertNotIn("1 of 5", out)
        self.assertNotIn("5 of 5", out)
        buf = io.StringIO()
        with redirect_stdout(buf):
            edgar.find_credit_agreements("SNBR", verbose=True)
        verbose_out = buf.getvalue()
        self.assertIn("1 of 5", verbose_out)
        self.assertIn("5 of 5", verbose_out)

    def test_accepts_cik(self):
        self._route_all_cik()
        cands, _ = self._find("827187")
        self.assertEqual(len(cands), 5)
        fetched = " ".join(u for u, _ in self.fetch.calls)
        self.assertNotIn("company_tickers.json", fetched)

    def test_titles(self):
        self._route_all()
        cands, _ = self._find()
        by_url = {c["url"].rsplit("/", 1)[-1]: c for c in cands}
        self.assertEqual(
            by_url["ex101-forbearance.htm"]["title"], "FORBEARANCE AGREEMENT"
        )
        # Uppercase AMENDMENT line wins even without an INCLUDE match.
        self.assertEqual(
            by_url["ex101creditagreement.htm"]["title"],
            "THIRTEENTH AMENDMENT TO",
        )
        self.assertEqual(
            by_url["ex102.htm"]["title"],
            "FOURTEENTH AMENDMENT TO CREDIT AGREEMENT",
        )
        self.assertEqual(
            by_url["ex101-credit.htm"]["title"],
            "SECOND AMENDED AND RESTATED CREDIT AGREEMENT",
        )
        self.assertEqual(
            by_url["ex101old.htm"]["title"],
            "AMENDMENT NO. 1 TO CREDIT AGREEMENT",
        )
        for cand in cands:
            self.assertLessEqual(len(cand["title"]), 150)
            self.assertTrue(cand["title"].strip())

    def test_forbearance_and_amendment_marked(self):
        self._route_all()
        cands, _ = self._find()
        by_url = {c["url"].rsplit("/", 1)[-1]: c for c in cands}
        self.assertTrue(by_url["ex101-forbearance.htm"]["is_forbearance"])
        self.assertFalse(by_url["ex101-forbearance.htm"]["is_amendment"])
        self.assertTrue(by_url["ex101creditagreement.htm"]["is_amendment"])
        self.assertFalse(by_url["ex101creditagreement.htm"]["is_forbearance"])
        self.assertTrue(by_url["ex102.htm"]["is_amendment"])
        self.assertTrue(by_url["ex101old.htm"]["is_amendment"])

    def test_generic_exhibit_included_by_text(self):
        self._route_all()
        cands, _ = self._find()
        urls = [c["url"] for c in cands]
        self.assertTrue(any(u.endswith("/ex102.htm") for u in urls))
        generic = next(c for c in cands if c["url"].endswith("/ex102.htm"))
        self.assertEqual(generic["description"], "ex102.htm")
        self.assertIn("CREDIT AGREEMENT", generic["title"])

    def test_struck_text_stripped(self):
        self._route_all()
        cands, _ = self._find()
        urls = " ".join(c["url"] for c in cands)
        # ex101old contains a struck-through lease line; with stripping it
        # classifies as a credit agreement amendment.
        self.assertIn("ex101old.htm", urls)

    def test_every_ex10_fetched(self):
        self._route_all()
        _, _ = self._find()
        fetched = " ".join(u for u, _ in self.fetch.calls)
        for docname in (
            "ex101-forbearance.htm",
            "ex101creditagreement.htm",
            "ex102.htm",
            "ex103-consulting.htm",
            "ex104-lease.htm",
            "ex105-executive.htm",
            "ex101-credit.htm",
            "ex101old.htm",
        ):
            self.assertIn(docname, fetched)
        self.assertNotIn("ex991earnings.htm", fetched)

    def test_exclude_wins_over_later_include(self):
        self._route_all()
        cands, _ = self._find()
        urls = " ".join(c["url"] for c in cands)
        # Consulting text mentions the Credit Agreement later, but consulting
        # in the first 500 characters excludes it.
        self.assertNotIn("ex103-consulting", urls)

    def test_title_trimmed_to_150_chars(self):
        long_line = "CREDIT AGREEMENT " + "X" * 200
        title = edgar._extract_title(long_line + "\nsecond line\n")
        self.assertEqual(len(title), 150)
        self.assertTrue(title.startswith("CREDIT AGREEMENT"))


class ClassifyPatterns(unittest.TestCase):
    def assert_included(self, text):
        self.assertTrue(
            edgar._matches_any(edgar.INCLUDE_RES, text), f"should include: {text!r}"
        )

    def assert_excluded_head(self, text):
        self.assertTrue(
            edgar._matches_any(edgar.EXCLUDE_RES, text), f"should exclude: {text!r}"
        )

    def test_include_patterns(self):
        self.assert_included("Credit Agreement")
        self.assert_included("CREDIT AND SECURITY AGREEMENT")
        self.assert_included("Credit and Guaranty Agreement")
        self.assert_included("Loan Agreement")
        self.assert_included("loan and security agreement")
        self.assert_included("Revolving Credit Facility")
        self.assert_included("TERM LOAN")
        self.assert_included("Forbearance Agreement")
        self.assert_included("Financing Agreement")
        self.assert_included("Note Purchase Agreement")
        # Case-insensitive.
        self.assert_included("cReDiT aGrEeMeNt")

    def test_exclude_patterns(self):
        for word in (
            "lease",
            "sublease",
            "employment",
            "executive",
            "severance",
            "separation",
            "compensation",
            "incentive",
            "award",
            "indemnification",
            "consulting",
            "supply",
            "license",
            "merger",
        ):
            self.assert_excluded_head(word)
            self.assert_excluded_head(word.upper())
        self.assert_excluded_head("purchase and sale")
        self.assert_excluded_head("PURCHASE AND SALE")


class Discover(DiscoverTestBase):
    def _route_all_cik(self):
        self.fetch.add("submissions/CIK", SUBMISSIONS)
        for docname, html in EXHIBIT_HTML.items():
            self.fetch.add(docname, html)
        for nodash, rows in INDEX_ROWS.items():
            self.fetch.add(nodash, _index_html(nodash, rows))

    def test_top_10(self):
        fake = [
            {
                "url": f"https://example.invalid/{i}",
                "filingDate": f"2025-01-{i + 1:02d}",
                "form": "8-K",
                "description": f"candidate {i}",
                "title": f"TITLE {i}",
                "is_forbearance": False,
                "is_amendment": False,
            }
            for i in range(12)
        ]
        with patch.object(edgar, "find_credit_agreements", return_value=fake):
            self.assertEqual(edgar.discover("SNBR"), fake[:10])
            self.assertEqual(edgar.discover("SNBR", limit=3), fake[:3])

    def test_accepts_cik(self):
        self._route_all_cik()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cands = edgar.discover("0000827187", limit=2)
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0]["filingDate"], "2026-01-15")
        fetched = " ".join(u for u, _ in self.fetch.calls)
        self.assertNotIn("company_tickers.json", fetched)

    def test_cli_prints_title_and_markers(self):
        fake = [
            {
                "url": "https://example.invalid/forbear",
                "filingDate": "2026-01-15",
                "form": "8-K",
                "description": "Forbearance Agreement dated January 2026",
                "title": "FORBEARANCE AGREEMENT",
                "is_forbearance": True,
                "is_amendment": False,
            },
            {
                "url": "https://example.invalid/amend",
                "filingDate": "2025-11-10",
                "form": "8-K",
                "description": "Second Amended and Restated Credit Agreement",
                "title": "CREDIT AND SECURITY AGREEMENT",
                "is_forbearance": False,
                "is_amendment": True,
            },
        ]
        with patch.object(edgar, "find_credit_agreements", return_value=fake):
            buf = io.StringIO()
            with redirect_stdout(buf):
                edgar.run_discover_cli("SNBR")
        out = buf.getvalue()
        self.assertIn("FORBEARANCE AGREEMENT", out)
        self.assertIn("CREDIT AND SECURITY AGREEMENT", out)
        self.assertIn("[FORBEARANCE]", out)
        self.assertIn("[AMENDMENT]", out)


class ExhibitTypeRegex(unittest.TestCase):
    def test_matches_ex10_variants(self):
        for typ in ("EX-10", "EX-10.1", "EX-10.2", "ex-10.10", " ex-10.1 "):
            self.assertTrue(
                bool(edgar.EXHIBIT_TYPE_RE.match(typ.strip())),
                f"should match: {typ!r}",
            )

    def test_rejects_xbrl_and_other(self):
        for typ in ("EX-101", "EX-101.SCH", "EX-101.CAL", "EX-99.1", "8-K", "EX-10.1/A"):
            self.assertFalse(
                bool(edgar.EXHIBIT_TYPE_RE.match(typ)),
                f"should reject: {typ!r}",
            )


class ExhibitTypeIntegration(DiscoverTestBase):
    def test_ex101_sch_excluded(self):
        subs = {
            "cik": "0000827187",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000827187-25-000123"],
                    "filingDate": ["2025-11-10"],
                    "reportDate": ["2025-11-10"],
                    "form": ["10-K"],
                    "primaryDocument": ["snbr-20251110.htm"],
                    "items": [""],
                }
            },
        }
        self.fetch.add("submissions/CIK", subs)
        nodash = "000082718725000123"
        rows = [
            {
                "name": "credit.htm",
                "type": "EX-10.1",
                "description": "Credit Agreement",
            },
            {
                "name": "xbrl.sch",
                "type": "EX-101.SCH",
                "description": "Credit Agreement XBRL",
            },
        ]
        self.fetch.add("credit.htm", EXHIBIT_HTML["ex101-credit.htm"])
        # Would be included by text if the type matched.
        self.fetch.add("xbrl.sch", EXHIBIT_HTML["ex101-credit.htm"])
        self.fetch.add(nodash, _index_html(nodash, rows))
        buf = io.StringIO()
        with redirect_stdout(buf):
            cands = edgar.find_credit_agreements("827187")
        urls = " ".join(c["url"] for c in cands)
        self.assertIn("credit.htm", urls)
        self.assertNotIn("xbrl.sch", urls)
        fetched = " ".join(u for u, _ in self.fetch.calls)
        self.assertNotIn("xbrl.sch", fetched)


class UppercaseTitle(unittest.TestCase):
    def test_uppercase_wins_over_mid_sentence_fragment(self):
        head = (
            "This amendment to the Credit Agreement, dated as of March 1, 2025,\n"
            "is entered into by and among the parties hereto.\n"
            "\n"
            "SECOND AMENDED AND RESTATED CREDIT AGREEMENT\n"
            "Dated as of March 1, 2025.\n"
        )
        self.assertEqual(
            edgar._extract_title(head),
            "SECOND AMENDED AND RESTATED CREDIT AGREEMENT",
        )

    def test_mixed_case_falls_back_to_include_match(self):
        head = (
            "This Credit Agreement is entered into as of March 1, 2025.\n"
            "Some other line here.\n"
        )
        self.assertEqual(
            edgar._extract_title(head),
            "This Credit Agreement is entered into as of March 1, 2025.",
        )

    def test_below_threshold_not_uppercase(self):
        # Only ~30% uppercase letters: not mostly uppercase.
        line = "Amendment to the credit agreement dated March 2025"
        self.assertFalse(edgar._is_mostly_uppercase(line))
        self.assertTrue(edgar._is_mostly_uppercase("AMENDMENT TO CREDIT AGREEMENT"))

    def test_beyond_1500_chars_ignored(self):
        first = "This Credit Agreement is entered into as of March 1, 2025."
        head = first + "\n" + "x" * 1600 + "\nCREDIT AGREEMENT\n"
        # Uppercase title beyond 1,500 chars does not win; fallback to
        # the first INCLUDE match (the mixed-case fragment).
        self.assertEqual(edgar._extract_title(head), first)


def _long_text(with_ebitda=True, with_covenant=True, length=160000, ebitda_means=False):
    parts = ["CREDIT AGREEMENT"]
    if with_ebitda:
        if ebitda_means:
            parts.append('"EBITDA" means net income plus interest, taxes and depreciation.')
        else:
            parts.append('"Consolidated EBITDA" means consolidated net income plus add-backs.')
    if with_covenant:
        parts.append("Section 7. Financial Covenant: the Leverage Ratio shall not exceed 3.50.")
    parts.append("X" * length)
    return "\n".join(parts) + "\n"


class IsCompleteUnit(unittest.TestCase):
    def test_true_with_consolidated_ebitda(self):
        self.assertTrue(edgar._is_complete_text(_long_text()))

    def test_true_with_ebitda_means(self):
        self.assertTrue(edgar._is_complete_text(_long_text(ebitda_means=True)))

    def test_false_when_short(self):
        self.assertFalse(edgar._is_complete_text(_long_text(length=100)))

    def test_false_without_ebitda(self):
        self.assertFalse(edgar._is_complete_text(_long_text(with_ebitda=False)))

    def test_false_without_covenant(self):
        self.assertFalse(edgar._is_complete_text(_long_text(with_covenant=False)))

    def test_true_with_coverage_ratio(self):
        text = (
            "CREDIT AGREEMENT\nConsolidated EBITDA defined herein.\n"
            "The Coverage Ratio shall be tested quarterly.\n" + "Y" * 160000
        )
        self.assertTrue(edgar._is_complete_text(text))


class IsCompleteIntegration(DiscoverTestBase):
    def test_top5_full_text_marks_complete(self):
        subs = {
            "cik": "0000827187",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000827187-25-000123"],
                    "filingDate": ["2025-11-10"],
                    "reportDate": ["2025-11-10"],
                    "form": ["10-K"],
                    "primaryDocument": ["snbr-20251110.htm"],
                    "items": [""],
                }
            },
        }
        self.fetch.add("submissions/CIK", subs)
        nodash = "000082718725000123"
        rows = [
            {"name": "big.htm", "type": "EX-10.1", "description": "Credit Agreement"},
            {"name": "small.htm", "type": "EX-10.2", "description": "Credit Agreement"},
        ]
        big_text = _long_text()
        big_html = (
            "<html><body><p>CREDIT AGREEMENT</p>"
            f"<p>{big_text[:5000]}</p><p>{'Z' * 160000}</p></body></html>"
        )
        # Ensure the full-text markers survive in the HTML version.
        big_html = (
            "<html><body><p>CREDIT AGREEMENT</p>"
            "<p>Consolidated EBITDA means consolidated net income.</p>"
            "<p>Section 7. Financial Covenant and Leverage Ratio tests.</p>"
            f"<p>{'Z' * 160000}</p></body></html>"
        )
        small_html = EXHIBIT_HTML["ex101-credit.htm"]
        self.fetch.add("big.htm", big_html)
        self.fetch.add("small.htm", small_html)
        self.fetch.add(nodash, _index_html(nodash, rows))
        buf = io.StringIO()
        with redirect_stdout(buf):
            cands = edgar.find_credit_agreements("827187")
        by_url = {c["url"].rsplit("/", 1)[-1]: c for c in cands}
        self.assertTrue(by_url["big.htm"]["is_complete"])
        self.assertGreater(by_url["big.htm"]["char_count"], 150000)
        self.assertEqual(
            by_url["big.htm"]["char_count"], by_url["big.htm"]["character_count"]
        )
        self.assertFalse(by_url["small.htm"]["is_complete"])


def _cand(filing_date, complete=False, amendment=False, name="ex.htm"):
    return {
        "url": f"https://example.invalid/{filing_date}/{name}",
        "filingDate": filing_date,
        "form": "8-K",
        "description": name,
        "title": "TITLE " + filing_date,
        "is_forbearance": False,
        "is_amendment": amendment,
        "is_complete": complete,
        "char_count": 200000 if complete else 5000,
        "character_count": 200000 if complete else 5000,
    }


class SelectAgreement(unittest.TestCase):
    def _fake(self):
        # Newest first, as find_credit_agreements returns.
        return [
            _cand("2025-11-10", complete=False, amendment=True, name="amend2.htm"),
            _cand("2025-10-01", complete=False, amendment=False, name="other.htm"),
            _cand("2025-09-27", complete=False, amendment=True, name="amend1.htm"),
            _cand("2025-03-01", complete=True, amendment=False, name="base.htm"),
            _cand("2024-01-15", complete=True, amendment=False, name="oldbase.htm"),
        ]

    def test_base_is_newest_complete(self):
        with patch.object(edgar, "find_credit_agreements", return_value=self._fake()):
            base, amendments = edgar.select_agreement("SNBR")
        self.assertEqual(base["filingDate"], "2025-03-01")
        self.assertTrue(base["is_complete"])

    def test_amendments_newer_oldest_first_excludes_non_amendment(self):
        with patch.object(edgar, "find_credit_agreements", return_value=self._fake()):
            base, amendments = edgar.select_agreement("SNBR")
        self.assertEqual(
            [c["filingDate"] for c in amendments], ["2025-09-27", "2025-11-10"]
        )
        for c in amendments:
            self.assertTrue(c["is_amendment"])
            self.assertFalse(c["is_complete"])

    def test_dict_style_access(self):
        with patch.object(edgar, "find_credit_agreements", return_value=self._fake()):
            result = edgar.select_agreement("SNBR")
        self.assertEqual(result["base"]["filingDate"], "2025-03-01")
        self.assertEqual(len(result["amendments"]), 2)
        self.assertEqual(result.base["filingDate"], "2025-03-01")
        self.assertEqual(len(result.amendments), 2)

    def test_as_of_filters_base_and_amendments(self):
        with patch.object(edgar, "find_credit_agreements", return_value=self._fake()):
            base, amendments = edgar.select_agreement("SNBR", as_of="2025-10-01")
        self.assertEqual(base["filingDate"], "2025-03-01")
        self.assertEqual([c["filingDate"] for c in amendments], ["2025-09-27"])

    def test_as_of_before_base_picks_older(self):
        with patch.object(edgar, "find_credit_agreements", return_value=self._fake()):
            base, amendments = edgar.select_agreement("SNBR", as_of="2025-01-01")
        self.assertEqual(base["filingDate"], "2024-01-15")
        self.assertEqual(amendments, [])

    def test_as_of_before_all_complete(self):
        with patch.object(edgar, "find_credit_agreements", return_value=self._fake()):
            base, amendments = edgar.select_agreement("SNBR", as_of="2023-01-01")
        self.assertIsNone(base)
        self.assertEqual(amendments, [])


class SelectCli(unittest.TestCase):
    def test_unknown_command_prints_usage(self):
        with patch.object(
            edgar, "main", side_effect=AssertionError("default download must not run")
        ):
            err = io.StringIO()
            with redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    edgar.main_cli(["edgar.py", "bogus"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("Usage", err.getvalue())

    def test_select_missing_ticker_prints_usage(self):
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                edgar.main_cli(["edgar.py", "select"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("Usage", err.getvalue())

    def test_select_cli_prints_base_and_amendments(self):
        base = _cand("2025-03-01", complete=True, name="base.htm")
        amend = _cand("2025-09-27", complete=False, amendment=True, name="amend1.htm")
        with patch.object(
            edgar, "select_agreement", return_value=(base, [amend])
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                edgar.run_select_cli("SNBR")
        out = buf.getvalue()
        self.assertIn("Base agreement", out)
        self.assertIn("is_complete", out)
        self.assertIn("200000", out)
        self.assertIn("characters", out)
        self.assertIn("Amendments to apply (1)", out)
        self.assertIn("2025-09-27", out)

    def test_no_args_still_runs_default_download(self):
        with patch.object(edgar, "main", return_value=(1, 0)) as m:
            edgar.main_cli(["edgar.py"])
        m.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
