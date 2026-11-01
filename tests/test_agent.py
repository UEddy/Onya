"""Focused tests for src/agent.py (mocked model client; no live calls)."""

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

import agent
import edgar


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name,
                                 arguments=json.dumps(arguments)))


def _response(content="", tool_calls=None, prompt=10, completion=5):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=content, tool_calls=tool_calls))],
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


def _covenant_result():
    return {
        "period_end": "2026-04-04", "units": "USD",
        "numerator": 962096000, "numerator_thousands": 962096,
        "ebitda": 43188000, "ebitda_thousands": 43188,
        "ebitdar": 146254000, "ebitdar_thousands": 146254,
        "disallowed": 18732000,
        "net_leverage": {"ratio": 6.578, "ratio_2dp": 6.58,
                         "threshold": 4.75, "headroom": -1.83,
                         "headroom_2dp": -1.83, "pass": False,
                         "note": "Net Leverage Ratio max 4.75"},
        "interest_coverage": {"ratio": 0.84, "ratio_2dp": 0.84,
                              "threshold": 2.1, "headroom": -1.26,
                              "headroom_2dp": -1.26, "pass": False,
                              "note": "Interest Coverage Ratio min 2.1"},
        "data_quality_warnings": [],
    }


class Schemas(unittest.TestCase):
    def test_six_tools_with_required_params(self):
        names = [s["function"]["name"] for s in agent.TOOL_SCHEMAS]
        self.assertEqual(sorted(names), [
            "compute_covenants", "cure_analysis", "draft_memo",
            "extract_covenants", "find_agreements", "lookup_company",
            "project_next_test"])
        required = {s["function"]["name"]: s["function"]["parameters"]["required"]
                    for s in agent.TOOL_SCHEMAS}
        self.assertEqual(required["lookup_company"], ["name_or_ticker"])
        self.assertEqual(required["find_agreements"], ["company"])
        self.assertEqual(required["extract_covenants"],
                         ["company", "agreement_url"])
        self.assertEqual(required["compute_covenants"],
                         ["company", "period_end"])
        self.assertEqual(required["project_next_test"],
                         ["company", "base_period"])
        self.assertEqual(required["cure_analysis"], ["company", "period_end"])
        self.assertEqual(required["draft_memo"],
                         ["company", "period_end", "draft"])

    def test_model_and_limits(self):
        self.assertEqual(agent.MODEL, "muse-spark-1.3")
        self.assertEqual(agent.MAX_TOKENS, 8000)
        self.assertEqual(agent.MAX_TOOL_CALLS, 15)
        self.assertEqual(agent.TOKEN_BUDGET, 400_000)

    def test_system_prompt_rules(self):
        prompt = agent.SYSTEM_PROMPT.lower()
        for word in ("never invent numbers", "unsupported",
                     "cite", "covenant"):
            self.assertIn(word, prompt)
        self.assertIn("try a different approach", prompt)
        self.assertIn("lookup_company", prompt)
        self.assertIn("retry with the cik", prompt)


class CompanyHelpers(unittest.TestCase):
    def test_slug_known(self):
        self.assertEqual(agent.company_slug("SNBR"), "snbr")
        self.assertEqual(agent.company_slug("Sleep Number"), "snbr")
        self.assertEqual(agent.company_slug("Sleep Number Corporation"), "snbr")

    def test_slug_other(self):
        self.assertEqual(agent.company_slug("Acme Corp"), "acmecorp")

    def test_resolve_ticker(self):
        self.assertEqual(agent.resolve_ticker("Sleep Number"), "SNBR")
        self.assertEqual(agent.resolve_ticker("snbr"), "SNBR")
        self.assertEqual(agent.resolve_ticker("AAPL"), "AAPL")

    def test_resolve_ticker_unknown_phrase(self):
        with patch.object(agent, "tool_lookup_company",
                          return_value={"candidates": [],
                                        "error": "no CIK found"}):
            with self.assertRaises(ValueError):
                agent.resolve_ticker("Some Unknown Company Name")

    def test_resolve_ticker_unknown_phrase_via_lookup(self):
        with patch.object(agent, "tool_lookup_company",
                          return_value={"query": "Acme United",
                                        "candidates": [{"cik": "2098",
                                                        "name": "ACME UNITED CORP",
                                                        "source": "ticker_list"}]}):
            self.assertEqual(agent.resolve_ticker("Acme United Corp"), "2098")

    def test_slug_accepts_cik(self):
        self.assertEqual(agent.company_slug("827187"), "snbr")
        self.assertEqual(agent.company_slug("0000827187"), "snbr")

    def test_resolve_ticker_accepts_cik(self):
        self.assertEqual(agent.resolve_ticker("827187"), "827187")
        self.assertEqual(agent.resolve_ticker("0000827187"), "0000827187")


class FindAgreements(unittest.TestCase):
    def test_compact_no_document_text(self):
        base = {"url": "https://sec.gov/u1", "filingDate": "2024-01-01",
                "form": "8-K", "description": "Credit Agreement",
                "title": "CREDIT AGREEMENT", "is_forbearance": False,
                "is_amendment": False, "is_complete": True,
                "char_count": 200000, "full_text": "X" * 5000}
        with patch.dict(sys.modules, {"edgar": SimpleNamespace(
                select_agreement=lambda *a, **k: (base, []))}):
            agent.reset_corpus()
            result = agent.tool_find_agreements("SNBR")
        self.assertEqual(result["ticker"], "SNBR")
        self.assertEqual(result["base"]["url"], "https://sec.gov/u1")
        self.assertNotIn("full_text", json.dumps(result))


class ExtractCovenantsReviewed(unittest.TestCase):
    def test_reviewed_file_returned_with_note(self):
        agent.reset_corpus()
        result = agent.tool_extract_covenants(
            "Sleep Number", "https://sec.gov/ignored")
        self.assertTrue(result["reviewed"])
        self.assertIn("reviewed", result["note"].lower())
        self.assertTrue(result["saved_path"].endswith(
            "snbr_covenants.reviewed.json"))
        names = [c["name"] for c in result["financial_covenants"]]
        self.assertIn("Net Leverage Ratio", names)
        self.assertIn("Consolidated EBITDA", result["definition_terms"])
        self.assertNotIn("quote", json.dumps(result))


class ExtractCovenantsFresh(unittest.TestCase):
    def test_download_textify_extract_verify(self):
        html = ("<html><body><p>The Net Leverage Ratio shall not exceed "
                "4.75 to 1.00 for the test period.</p></body></html>")
        parsed = {"borrower": "ACME",
                  "agreement": {"title": "CREDIT AGREEMENT"},
                  "financial_covenants": [{
                      "id": "lev", "name": "Net Leverage Ratio",
                      "section": "5.7", "direction": "max",
                      "metric_term": "Net Leverage Ratio", "unit": "ratio",
                      "thresholds": [{"period_end": "2026-04-04",
                                      "applies_after": None, "value": 4.75,
                                      "condition": None}],
                      "quote": "Net Leverage Ratio shall not exceed 4.75"}],
                  "cap_groups": [],
                  "definitions": [{"term": "Net Leverage Ratio",
                                   "quote": "Net Leverage Ratio shall not exceed 4.75"}]}
        fetch_calls = {}

        def fake_fetch(url, filename):
            fetch_calls["url"] = url
            path = Path(tempfile.mkdtemp()) / filename
            path.write_bytes(html.encode())
            return path

        fake_llm = FakeClient([_response(content=json.dumps(parsed))])
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.dict(sys.modules, {"edgar": SimpleNamespace(
                     fetch=fake_fetch)}),
                  patch.object(agent, "DATA_DIR", Path(tmp))):
                agent.reset_corpus()
                result = agent.tool_extract_covenants(
                    "Acme Test", "https://sec.gov/u9", client=fake_llm)
        self.assertFalse(result["reviewed"])
        self.assertEqual(fetch_calls["url"], "https://sec.gov/u9")
        self.assertEqual(result["verified"], 2)
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["saved_path"].endswith(
            "acmetest_covenants.json"))
        self.assertEqual(result["financial_covenants"][0]["thresholds"][0]["value"], 4.75)


class ComputeCovenants(unittest.TestCase):
    def setUp(self):
        agent.reset_corpus()

    def test_unsupported_company(self):
        result = agent.tool_compute_covenants("Acme", "2026-04-04")
        self.assertFalse(result["supported"])
        self.assertIn("SNBR", result["reason"])

    def test_snbr_summary(self):
        with (patch.object(agent.covenant, "compute",
                            return_value=_covenant_result()),
              patch.object(agent.covenant, "save_result",
                            return_value=Path("/tmp/x.json"))):
            result = agent.tool_compute_covenants("SNBR", "2026-04-04")
        self.assertTrue(result["supported"])
        self.assertEqual(result["net_leverage"]["ratio_2dp"], 6.58)
        self.assertFalse(result["net_leverage"]["pass"])
        self.assertEqual(result["interest_coverage"]["threshold"], 2.1)
        self.assertEqual(result["flags"]["warning_count"], 0)
        self.assertNotIn("components", result)

    def test_compute_error_reported_not_fabricated(self):
        with patch.object(agent.covenant, "compute",
                          side_effect=ValueError("missing release line")):
            result = agent.tool_compute_covenants("SNBR", "2026-04-04")
        self.assertIn("missing release line", result["error"])


class ProjectAndCure(unittest.TestCase):
    def setUp(self):
        agent.reset_corpus()

    def test_project_unsupported(self):
        result = agent.tool_project_next_test("Acme", "2026-01-03")
        self.assertFalse(result["supported"])

    def test_project_summary(self):
        payload = {"base": "2026-01-03", "next_test": "2026-04-04",
                   "next_threshold": 4.75, "threshold_note": "n",
                   "ix_cap": 44000000, "ix_note": "i", "iv_viii_cap": 1,
                   "projected_proforma": 44000000,
                   "projections": {
                       "onya": {"ratio_2dp": 6.1, "threshold": 4.75,
                                "pass": False, "ebitdar": 100},
                       "company": {"ratio_2dp": 5.9, "threshold": 4.75,
                                   "pass": False, "ebitdar": 110}},
                   "cushion": {"onya": -5}, "quarters_of_cushion": {"onya": 1.2},
                   "risk": {"onya": "HIGH"}, "risk_rule": "r",
                   "trend": {"avg_decline": -3, "series": []},
                   "backtest": None}
        with (patch.object(agent.project, "compute", return_value=payload),
              patch.object(agent.project, "save_result",
                            return_value=Path("/tmp/p.json"))):
            result = agent.tool_project_next_test("SNBR", "2026-01-03")
        self.assertEqual(result["next_test"], "2026-04-04")
        self.assertEqual(result["risk"]["onya"], "HIGH")

    def test_cure_unsupported(self):
        result = agent.tool_cure_analysis("Acme", "2026-04-04")
        self.assertFalse(result["supported"])

    def test_cure_summary(self):
        payload = {"period_end": "2026-04-04", "units": "USD",
                   "interest": {"value": 51404000},
                   "base": {
                       "net_leverage": {
                           "status": "fail",
                           "figures": {"debt_reduction_needed":
                                       {"value": 267389500.0}},
                           "summary": "debt must fall by $267,389,500"},
                       "interest_coverage": {
                           "status": "fail", "figures": {},
                           "summary": "coverage fails"}},
                   "equity_cure": {"found": False,
                                   "note": "equity cure: not found"}}
        with (patch.object(agent.cure, "compute", return_value=payload),
              patch.object(agent.cure, "save_result",
                            return_value=Path("/tmp/c.json"))):
            result = agent.tool_cure_analysis("SNBR", "2026-04-04")
        self.assertEqual(result["base"]["net_leverage"]["status"], "fail")
        self.assertEqual(result["base"]["net_leverage"]["figures"][
            "debt_reduction_needed"], 267389500.0)
        self.assertFalse(result["equity_cure"]["found"])


class DraftMemo(unittest.TestCase):
    def setUp(self):
        agent.reset_corpus()

    def test_needs_draft_without_prose(self):
        result = agent.tool_draft_memo("SNBR", "2026-04-04")
        self.assertTrue(result["needs_draft"])

    def test_verified_numbers_pass(self):
        agent._record({"net_leverage": {"ratio_2dp": 6.58, "threshold": 4.75,
                                        "pass": False},
                       "numerator": 962096000, "period_end": "2026-04-04"})
        draft = ("As of 2026-04-04, leverage is 6.58x against a 4.75 max "
                 "with debt of $962,096,000.")
        result = agent.tool_draft_memo("SNBR", "2026-04-04", draft=draft)
        self.assertTrue(result["verified"])
        self.assertEqual(result["unverified_numbers"], [])

    def test_invented_number_flagged(self):
        agent._record({"net_leverage": {"ratio_2dp": 6.58, "threshold": 4.75}})
        draft = "Leverage is 6.58x and will fall to 3.25x next quarter."
        result = agent.tool_draft_memo("SNBR", "2026-04-04", draft=draft)
        self.assertFalse(result["verified"])
        self.assertIn("3.25x", result["unverified_numbers"])

    def test_m_suffix_rounding_accepted(self):
        agent._record({"figures": {"debt_reduction_needed": 267389500.0}})
        draft = "Debt must fall by about $267.4M to pass."
        result = agent.tool_draft_memo("SNBR", "2026-04-04", draft=draft)
        self.assertTrue(result["verified"])

    def test_memo_not_added_to_corpus(self):
        agent._record({"ratio_2dp": 6.58})
        agent.tool_draft_memo("SNBR", "2026-04-04",
                              draft="Leverage is 6.58x.")
        second = agent.tool_draft_memo(
            "SNBR", "2026-04-04", draft="Leverage is still 6.58x.")
        self.assertTrue(second["verified"])
        self.assertEqual(len(agent._TOOL_OUTPUTS), 1)


class AgentLoop(unittest.TestCase):
    def _run(self, script, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(agent, "RUNS_DIR", Path(tmp)):
                return agent.run_agent("Check SNBR", client=FakeClient(script),
                                       run_id="testrun", **kwargs)

    def test_tool_call_then_answer_and_trace(self):
        script = [
            _response(tool_calls=[_tool_call(
                "c1", "compute_covenants",
                {"company": "SNBR", "period_end": "2026-04-04"})]),
            _response(content="Leverage fails at 6.58x vs 4.75 max."),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(agent, "RUNS_DIR", Path(tmp)),
                  patch.object(agent.covenant, "compute",
                                return_value=_covenant_result()),
                  patch.object(agent.covenant, "save_result",
                                return_value=Path("/tmp/x.json"))):
                outcome = agent.run_agent("Check SNBR",
                                          client=FakeClient(script),
                                          run_id="t1")
            lines = (Path(tmp) / "t1.jsonl").read_text().strip().splitlines()
        self.assertEqual(outcome["reason"], "done")
        self.assertEqual(outcome["tool_calls"], 1)
        self.assertEqual(outcome["total_tokens"], 30)
        self.assertIn("6.58x", outcome["answer"])
        entries = [json.loads(line) for line in lines]
        kinds = [e["type"] for e in entries]
        self.assertEqual(kinds[0], "run_start")
        self.assertIn("tool_call", kinds)
        self.assertEqual(kinds[-1], "run_end")
        tool_entry = next(e for e in entries if e["type"] == "tool_call")
        for key in ("tool", "arguments", "result_summary", "tokens",
                    "timestamp", "total_tokens"):
            self.assertIn(key, tool_entry)
        self.assertEqual(tool_entry["tool"], "compute_covenants")
        self.assertIn("6.58", tool_entry["result_summary"])

    def test_request_uses_model_and_max_tokens(self):
        client = FakeClient([_response(content="hi")])
        self._run_script(client)
        req = client.chat.completions.requests[0]
        self.assertEqual(req["model"], "muse-spark-1.3")
        self.assertEqual(req["max_tokens"], 8000)
        self.assertEqual(len(req["tools"]), 7)

    def _run_script(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(agent, "RUNS_DIR", Path(tmp)):
                return agent.run_agent("hi", client=client, run_id="t0")

    def test_max_tool_calls_stops_with_summary(self):
        script = [_response(tool_calls=[_tool_call(
            f"c{i}", "compute_covenants",
            {"company": "Acme", "period_end": "2026-04-04"})])
            for i in range(15)]
        script.append(_response(content="Summary after fifteen calls."))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(agent, "RUNS_DIR", Path(tmp)):
                outcome = agent.run_agent("Check Acme",
                                          client=FakeClient(script),
                                          run_id="tmax")
        self.assertEqual(outcome["reason"], "max_tool_calls")
        self.assertEqual(outcome["tool_calls"], 15)
        self.assertIn("Summary", outcome["answer"])

    def test_token_budget_guard(self):
        script = [_response(content="x", prompt=300_000, completion=150_000)]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(agent, "RUNS_DIR", Path(tmp)):
                outcome = agent.run_agent("Check SNBR",
                                          client=FakeClient(script),
                                          run_id="tbud")
        self.assertEqual(outcome["reason"], "token_budget_exceeded")
        self.assertIn("budget", outcome["answer"])

    def test_unknown_tool_becomes_error_result(self):
        script = [_response(tool_calls=[_tool_call("c1", "nope", {})]),
                  _response(content="done")]
        outcome = self._run(script)
        self.assertEqual(outcome["reason"], "done")
        self.assertEqual(outcome["tool_calls"], 1)


FIXTURE_COMPANY_TABLE = """<html><body><div id="contentDiv">
<span class="companyMatch">Companies with names matching "ACME"</span>
<div id="seriesDiv"><table class="tableFile2" summary="Results">
<tr><th scope="col"><acronym title="Central Index Key">CIK</acronym></th>
<th scope="col">Company</th><th scope="col">State/Country</th></tr>
<tr><td valign="top" scope="row"><a href="/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001092013&amp;owner=include">0001092013</a></td>
<td scope="row">ACME COMMUNICATIONS INC<br /><acronym title="Standard Industrial Code">SIC</acronym>: 4833</td>
<td valign="top" scope="row">CA</td></tr>
<tr class="evenRow"><td valign="top" scope="row"><a href="/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0000002070&amp;owner=include">0000002070</a></td>
<td scope="row">ACME ELECTRIC CORP (inactive)<br /><acronym title="Standard Industrial Code">SIC</acronym>: 3620</td>
<td valign="top" scope="row">NY</td></tr>
</table></div></div></body></html>"""

FIXTURE_SINGLE_COMPANY = """<html><body><div class="companyInfo">
<span class="companyName">Sleep Number Corp <acronym title="Central Index Key">CIK</acronym>#: <a href="/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0000827187&amp;owner=include">0000827187 (see all company filings)</a></span>
</div></body></html>"""


class LookupCompanyRegistry(unittest.TestCase):
    def test_delisted_ticker_resolves_via_registry_without_network(self):
        def no_network(*a, **k):
            raise AssertionError("registry hit should not touch the network")

        with patch.dict(sys.modules, {"edgar": SimpleNamespace(
                fetch=no_network,
                TICKERS_URL="https://example.invalid/tickers.json")}):
            agent.reset_corpus()
            result = agent.tool_lookup_company("SNBR")
        self.assertEqual(result["query"], "SNBR")
        self.assertGreaterEqual(len(result["candidates"]), 1)
        cand = result["candidates"][0]
        self.assertEqual(cand["cik"], "827187")
        self.assertIn("Sleep Number", cand["name"])
        self.assertEqual(cand["source"], "registry")
        self.assertEqual(cand["found_via"], "registry")
        self.assertEqual(cand["how"], "registry")

    def test_registry_matches_name_and_cik_forms(self):
        agent.reset_corpus()
        by_name = agent.tool_lookup_company("Sleep Number Corp")
        self.assertEqual(by_name["candidates"][0]["cik"], "827187")
        self.assertEqual(by_name["candidates"][0]["source"], "registry")
        agent.reset_corpus()
        by_cik = agent.tool_lookup_company("0000827187")
        self.assertEqual(by_cik["candidates"][0]["cik"], "827187")
        self.assertEqual(by_cik["candidates"][0]["source"], "registry")

    def test_compute_accepts_cik(self):
        with (patch.object(agent.covenant, "compute",
                            return_value=_covenant_result()),
              patch.object(agent.covenant, "save_result",
                            return_value=Path("/tmp/x.json"))):
            agent.reset_corpus()
            result = agent.tool_compute_covenants("827187", "2026-04-04")
        self.assertTrue(result["supported"])
        self.assertEqual(result["net_leverage"]["ratio_2dp"], 6.58)


class BrowseEdgarParsing(unittest.TestCase):
    def test_company_table_includes_inactive(self):
        parsed = agent._parse_browse_edgar_html(FIXTURE_COMPANY_TABLE)
        self.assertEqual(len(parsed), 2)
        by_cik = {p["cik"]: p for p in parsed}
        self.assertIn("1092013", by_cik)
        self.assertIn("2070", by_cik)
        self.assertEqual(by_cik["1092013"]["name"],
                         "ACME COMMUNICATIONS INC")
        self.assertIn("inactive", by_cik["2070"]["name"].lower())

    def test_single_company_page(self):
        parsed = agent._parse_browse_edgar_html(FIXTURE_SINGLE_COMPANY)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["cik"], "827187")
        self.assertEqual(parsed[0]["name"], "Sleep Number Corp")

    def test_lookup_uses_edgar_search_when_registry_and_tickers_miss(self):
        seen_urls = []

        def fake_fetch(url, filename):
            seen_urls.append(url)
            path = Path(tempfile.mkdtemp()) / filename
            if "company_tickers" in url:
                path.write_text("{}", encoding="utf-8")
            else:
                self.assertIn("browse-edgar?company=", url)
                self.assertIn("action=getcompany", url)
                path.write_text(FIXTURE_COMPANY_TABLE, encoding="utf-8")
            return path

        with tempfile.TemporaryDirectory() as tmp:
            with (patch.dict(sys.modules, {"edgar": SimpleNamespace(
                     fetch=fake_fetch,
                     TICKERS_URL="https://www.sec.gov/files/company_tickers.json")}),
                  patch.object(agent, "DATA_DIR", Path(tmp))):
                agent.reset_corpus()
                result = agent.tool_lookup_company("ACME")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["candidates"][0]["cik"], "1092013")
        self.assertEqual(result["candidates"][0]["source"], "edgar_search")
        self.assertTrue(any("browse-edgar" in u for u in seen_urls))


class RetryAfterError(unittest.TestCase):
    def test_find_fail_then_lookup_then_retry_with_cik(self):
        base = {"url": "https://sec.gov/u1", "filingDate": "2024-01-01",
                "form": "8-K", "description": "Credit Agreement",
                "title": "CREDIT AGREEMENT", "is_forbearance": False,
                "is_amendment": False, "is_complete": True,
                "char_count": 200000}

        def fake_select(ticker, as_of=None):
            if ticker == "SNBR":
                raise ValueError("Unknown ticker 'SNBR': company may be "
                                 "delisted; pass the CIK instead.")
            if ticker == "827187":
                return base, []
            raise AssertionError(f"unexpected ticker {ticker!r}")

        script = [
            _response(tool_calls=[_tool_call(
                "c1", "find_agreements", {"company": "SNBR"})]),
            _response(tool_calls=[_tool_call(
                "c2", "lookup_company", {"name_or_ticker": "SNBR"})]),
            _response(tool_calls=[_tool_call(
                "c3", "find_agreements", {"company": "827187"})]),
            _response(content="Found the base agreement via CIK 827187."),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(agent, "RUNS_DIR", Path(tmp)),
                  patch.dict(sys.modules, {"edgar": SimpleNamespace(
                      select_agreement=fake_select)})):
                outcome = agent.run_agent(
                    "Find Sleep Number agreements",
                    client=FakeClient(script), run_id="tretry")
            lines = (Path(tmp) / "tretry.jsonl").read_text().strip().splitlines()
        self.assertEqual(outcome["reason"], "done")
        self.assertEqual(outcome["tool_calls"], 3)
        self.assertIn("827187", outcome["answer"])
        entries = [json.loads(line) for line in lines]
        tool_entries = [e for e in entries if e["type"] == "tool_call"]
        self.assertEqual(len(tool_entries), 3)
        self.assertIn("delisted", tool_entries[0]["result_summary"])
        self.assertIn("827187", tool_entries[1]["result_summary"])
        self.assertIn("base:", tool_entries[2]["result_summary"])


class EmptyFinalFallback(unittest.TestCase):
    def _run(self, script, **kwargs):
        client = FakeClient(script)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(agent, "RUNS_DIR", Path(tmp)):
                outcome = agent.run_agent("Check SNBR", client=client,
                                          run_id="tempty", **kwargs)
        return outcome, client

    def test_empty_twice_gives_fallback_summary(self):
        outcome, client = self._run([_response(content=""),
                                     _response(content="  ")])
        self.assertEqual(outcome["reason"], "done")
        self.assertTrue(outcome["answer"].strip())
        for word in ("What was tried", "What failed", "Why"):
            self.assertIn(word, outcome["answer"])
        retry_msg = client.chat.completions.requests[1]["messages"][-1]
        self.assertEqual(retry_msg["role"], "user")
        self.assertEqual(retry_msg["content"],
                         "Give your final answer now, citing tool results.")

    def test_empty_then_answer_returns_answer(self):
        outcome, client = self._run([_response(content=""),
                                     _response(content="Final: leverage 6.58x.")])
        self.assertEqual(outcome["answer"], "Final: leverage 6.58x.")
        self.assertEqual(len(client.chat.completions.requests), 2)

    def test_fallback_mentions_tool_history(self):
        script = [
            _response(tool_calls=[_tool_call(
                "c1", "compute_covenants",
                {"company": "SNBR", "period_end": "2026-04-04"})]),
            _response(content=""),
            _response(content=""),
        ]
        client = FakeClient(script)
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(agent, "RUNS_DIR", Path(tmp)),
                  patch.object(agent.covenant, "compute",
                                return_value=_covenant_result()),
                  patch.object(agent.covenant, "save_result",
                                return_value=Path("/tmp/x.json"))):
                outcome = agent.run_agent("Check SNBR", client=client,
                                          run_id="tempty2")
        self.assertTrue(outcome["answer"].strip())
        self.assertIn("compute_covenants", outcome["answer"])
        self.assertIn("What was tried", outcome["answer"])


class Dispatch(unittest.TestCase):
    def test_unknown_tool(self):
        self.assertIn("unknown tool", agent.dispatch_tool("nope", {})["error"])

    def test_bad_arguments(self):
        result = agent.dispatch_tool("compute_covenants", {"company": "SNBR"})
        self.assertIn("bad arguments", result["error"])


def _base_candidate():
    return {"url": "https://sec.gov/u1", "filingDate": "2024-01-01",
            "form": "8-K", "description": "Credit Agreement",
            "title": "CREDIT AGREEMENT", "is_forbearance": False,
            "is_amendment": False, "is_complete": True,
            "char_count": 200000}


class AsOfDiscipline(unittest.TestCase):
    def test_all_schemas_take_as_of(self):
        for schema in agent.TOOL_SCHEMAS:
            name = schema["function"]["name"]
            props = schema["function"]["parameters"]["properties"]
            self.assertIn("as_of", props, f"{name} schema lacks as_of")

    def test_reporting_as_of_adds_45_days(self):
        self.assertEqual(agent.reporting_as_of("2026-04-04"), "2026-05-19")
        self.assertEqual(agent.reporting_as_of("2025-12-01"), "2026-01-15")

    def test_system_prompt_reporting_window(self):
        prompt = agent.SYSTEM_PROMPT.lower()
        self.assertIn("45 days", prompt)
        self.assertIn("reporting window", prompt)
        self.assertIn("find_agreements", prompt)
        self.assertIn("as_of", prompt)

    def test_lookup_hides_registry_status(self):
        agent.reset_corpus()
        result = agent.tool_lookup_company("SNBR")
        self.assertGreaterEqual(len(result["candidates"]), 1)
        for cand in result["candidates"]:
            self.assertNotIn("status", cand)
        self.assertNotIn("Chapter 11", json.dumps(result))

    def test_lookup_accepts_as_of(self):
        agent.reset_corpus()
        result = agent.tool_lookup_company("SNBR", as_of="2026-05-19")
        self.assertEqual(result["as_of"], "2026-05-19")
        self.assertEqual(result["candidates"][0]["cik"], "827187")

    def test_find_passes_as_of_to_select(self):
        seen = {}

        def fake_select(ticker, as_of=None):
            seen["ticker"] = ticker
            seen["as_of"] = as_of
            return _base_candidate(), []

        with patch.dict(sys.modules, {"edgar": SimpleNamespace(
                select_agreement=fake_select)}):
            agent.reset_corpus()
            result = agent.tool_find_agreements("SNBR", as_of="2026-05-19")
        self.assertEqual(seen["as_of"], "2026-05-19")
        self.assertEqual(result["as_of"], "2026-05-19")

    def test_compute_rejects_period_after_as_of(self):
        with patch.object(agent.covenant, "compute",
                          side_effect=AssertionError("must not compute")):
            agent.reset_corpus()
            result = agent.tool_compute_covenants(
                "SNBR", "2026-04-04", as_of="2026-01-03")
        self.assertIn("as_of", result["error"])
        self.assertIn("2026-04-04", result["error"])

    def test_compute_echoes_as_of(self):
        with (patch.object(agent.covenant, "compute",
                            return_value=_covenant_result()),
              patch.object(agent.covenant, "save_result",
                            return_value=Path("/tmp/x.json"))):
            agent.reset_corpus()
            result = agent.tool_compute_covenants(
                "SNBR", "2026-04-04", as_of="2026-05-19")
        self.assertEqual(result["as_of"], "2026-05-19")

    def test_project_and_cure_reject_period_after_as_of(self):
        agent.reset_corpus()
        proj = agent.tool_project_next_test(
            "SNBR", "2026-04-04", as_of="2026-01-03")
        self.assertIn("as_of", proj["error"])
        agent.reset_corpus()
        cure = agent.tool_cure_analysis("SNBR", "2026-04-04",
                                        as_of="2026-01-03")
        self.assertIn("as_of", cure["error"])

    def test_extract_and_memo_accept_as_of(self):
        agent.reset_corpus()
        extracted = agent.tool_extract_covenants(
            "Sleep Number", "https://sec.gov/ignored", as_of="2026-05-19")
        self.assertEqual(extracted["as_of"], "2026-05-19")
        agent.reset_corpus()
        agent._record({"ratio_2dp": 6.58})
        memo = agent.tool_draft_memo("SNBR", "2026-04-04",
                                     draft="Leverage is 6.58x.",
                                     as_of="2026-05-19")
        self.assertEqual(memo["as_of"], "2026-05-19")
        self.assertTrue(memo["verified"])


class ComputeLabels(unittest.TestCase):
    def test_compute_returns_explicit_labels(self):
        with (patch.object(agent.covenant, "compute",
                            return_value=_covenant_result()),
              patch.object(agent.covenant, "save_result",
                            return_value=Path("/tmp/x.json"))):
            agent.reset_corpus()
            result = agent.tool_compute_covenants("SNBR", "2026-04-04")
        labels = result["labels"]
        self.assertEqual(labels["numerator"],
                         "total debt including operating lease liabilities")
        self.assertIn("funded indebtedness", list(labels.values()))

    def test_system_prompt_exact_titles_rule(self):
        prompt = agent.SYSTEM_PROMPT.lower()
        self.assertIn("exact titles and labels", prompt)
        self.assertIn("never name or number an amendment", prompt)


class DraftMemoLabels(unittest.TestCase):
    def setUp(self):
        agent.reset_corpus()

    def test_invented_ordinal_flagged(self):
        agent._record({"title": "CREDIT AGREEMENT"})
        result = agent.tool_draft_memo(
            "SNBR", "2026-04-04",
            draft="The thirteenth amendment raises the cap.")
        self.assertFalse(result["verified"])
        self.assertIn("thirteenth amendment",
                      result["unverified_ordinals"])

    def test_ordinal_from_tools_passes(self):
        agent._record({"title": "THIRTEENTH AMENDMENT TO CREDIT AGREEMENT"})
        result = agent.tool_draft_memo(
            "SNBR", "2026-04-04",
            draft="The thirteenth amendment raises the cap.")
        self.assertEqual(result["unverified_ordinals"], [])
        self.assertTrue(result["verified"])

    def test_numbered_amendment_flagged(self):
        agent._record({"title": "CREDIT AGREEMENT"})
        result = agent.tool_draft_memo(
            "SNBR", "2026-04-04",
            draft="Amendment No. 14 raises the cap.")
        self.assertFalse(result["verified"])
        self.assertTrue(any("14" in o for o in result["unverified_ordinals"]))

    def test_invented_title_flagged(self):
        agent._record({"title": "CREDIT AGREEMENT"})
        result = agent.tool_draft_memo(
            "SNBR", "2026-04-04",
            draft='Under the "Second Lien Credit Agreement", risk is high.')
        self.assertFalse(result["verified"])
        self.assertTrue(any("Second Lien" in t
                            for t in result["unverified_titles"]))

    def test_title_from_tools_passes(self):
        agent._record({"title": "FORBEARANCE AGREEMENT"})
        result = agent.tool_draft_memo(
            "SNBR", "2026-04-04",
            draft='Under the "Forbearance Agreement", risk is high.')
        self.assertEqual(result["unverified_titles"], [])
        self.assertTrue(result["verified"])


class ReconciliationUnavailable(unittest.TestCase):
    def test_compute_reconciliation_not_available(self):
        with (patch.object(agent.covenant, "compute",
                            return_value=_covenant_result()),
              patch.object(agent.covenant, "save_result",
                            return_value=Path("/tmp/x.json"))):
            agent.reset_corpus()
            result = agent.tool_compute_covenants("SNBR", "2026-04-04")
        self.assertEqual(
            result["flags"]["reconciliation"],
            "not available (no company leverage table disclosed)")

    def test_compute_reconciliation_present_unchanged(self):
        payload = _covenant_result()
        payload["reconciliation"] = {
            "company_ebitda": 100, "onya_ebitda": 90, "difference": 10,
            "status": "reconciled", "note": "n",
            "net_leverage": {
                "company_reported": {"ratio_2dp": 5.0, "pass": False},
                "onya_strict": {"ratio_2dp": 6.0, "pass": False}}}
        with (patch.object(agent.covenant, "compute", return_value=payload),
              patch.object(agent.covenant, "save_result",
                            return_value=Path("/tmp/x.json"))):
            agent.reset_corpus()
            result = agent.tool_compute_covenants("SNBR", "2026-04-04")
        rec = result["flags"]["reconciliation"]
        self.assertIsInstance(rec, dict)
        self.assertEqual(rec["status"], "reconciled")

    def test_system_prompt_no_break_rule(self):
        self.assertIn("not available (no company leverage table disclosed)",
                      agent.SYSTEM_PROMPT)
        self.assertIn('"no break"', agent.SYSTEM_PROMPT.lower())


class QuietMode(unittest.TestCase):
    def test_tool_find_agreements_suppresses_progress(self):
        def noisy_select(ticker, as_of=None):
            print("Checking filing 1 of 3: 8-K 2025-11-10 abc")
            print("Skipping 2 8-K(s) without item 1.01/2.03; checking 1 of 3 filings")
            return _base_candidate(), []

        with patch.dict(sys.modules, {"edgar": SimpleNamespace(
                select_agreement=noisy_select)}):
            agent.reset_corpus()
            buf = io.StringIO()
            with redirect_stdout(buf):
                agent.tool_find_agreements("SNBR")
        self.assertEqual(buf.getvalue(), "")

    def test_find_credit_agreements_quiet_by_default(self):
        filings = [{"form": "8-K", "filingDate": "2025-11-10",
                    "accessionNumber": "0000827187-25-000123",
                    "primaryDocument": "snbr-20251110.htm",
                    "reportDate": "2025-11-10", "items": "1.01"}]
        with (patch.object(edgar, "list_filings", return_value=filings),
              patch.object(edgar, "filing_documents", return_value=[])):
            buf = io.StringIO()
            with redirect_stdout(buf):
                edgar.find_credit_agreements("827187")
            self.assertNotIn("Checking filing", buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                edgar.find_credit_agreements("827187", verbose=True)
            self.assertIn("Checking filing 1 of 1", buf.getvalue())

    def test_cli_discover_still_prints_progress(self):
        filings = [{"form": "8-K", "filingDate": "2025-11-10",
                    "accessionNumber": "0000827187-25-000123",
                    "primaryDocument": "snbr-20251110.htm",
                    "reportDate": "2025-11-10", "items": "1.01"}]
        with (patch.object(edgar, "list_filings", return_value=filings),
              patch.object(edgar, "filing_documents", return_value=[])):
            buf = io.StringIO()
            with redirect_stdout(buf):
                edgar.run_discover_cli("827187")
        self.assertIn("Checking filing 1 of 1", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
