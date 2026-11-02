"""Tests for src/api.py (FastAPI TestClient; agent runs mocked)."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import agent  # noqa: E402
import api  # noqa: E402
import limits  # noqa: E402

TOKEN = "test-token-123"

TICKERS = {"TRS", "AIN", "AMCX", "STGW", "QUAD", "CRS", "ORLY", "GPK",
           "NUVR", "HAIN", "SNBR", "OPTX"}


def _stream_events(response):
    """Parse a newline-delimited JSON stream body into event dicts."""
    events = []
    for line in response.text.splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


class ApiTestBase(unittest.TestCase):
    def setUp(self):
        self._old_token = os.environ.get("ONYA_DEMO_TOKEN")
        os.environ["ONYA_DEMO_TOKEN"] = TOKEN
        api._reset_state()
        self.client = TestClient(api.app)

    def tearDown(self):
        if self._old_token is None:
            os.environ.pop("ONYA_DEMO_TOKEN", None)
        else:
            os.environ["ONYA_DEMO_TOKEN"] = self._old_token
        api._reset_state()

    def auth(self):
        return {"X-Onya-Token": TOKEN}

    def fake_run(self, answer="CANNED ANSWER", tokens=100, tool_calls=1,
                 reason="done"):
        def _fake(question, run_id=None, on_event=None, **kwargs):
            for entry in (
                    {"run_id": run_id, "step": 0,
                     "timestamp": "2026-01-01T00:00:00+00:00",
                     "type": "run_start", "tool": None, "arguments": {},
                     "result_summary": question[:300],
                     "tokens": {"prompt": 0, "completion": 0, "total": 0},
                     "total_tokens": 0},
                    {"run_id": run_id, "step": 1,
                     "timestamp": "2026-01-01T00:00:01+00:00",
                     "type": "tool_call", "tool": "lookup_company",
                     "arguments": {"name_or_ticker": "SNBR"},
                     "result_summary": "SNBR: 1 candidate(s)",
                     "tokens": {"prompt": 10, "completion": 5, "total": 15},
                     "total_tokens": 15}):
                if on_event is not None:
                    on_event(entry)
            return {"answer": answer, "reason": reason, "run_id": run_id,
                    "tool_calls": tool_calls, "total_tokens": tokens,
                    "figure_fields": []}
        return _fake


class Health(ApiTestBase):
    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})
        self.assertIn("application/json", r.headers["content-type"])


class Companies(ApiTestBase):
    def test_twelve_companies(self):
        r = self.client.get("/companies")
        self.assertEqual(r.status_code, 200)
        rows = r.json()["companies"]
        self.assertEqual(len(rows), 12)
        self.assertEqual({c["ticker"] for c in rows}, TICKERS)
        for c in rows:
            for key in ("ticker", "name", "period_end", "as_of", "covenant",
                        "ratio", "threshold", "headroom", "status"):
                self.assertIn(key, c, c["ticker"])
            self.assertIn(c["status"], ("pass", "fail", "unknown"))
            self.assertEqual(c["as_of"], c["period_end"], c["ticker"])

    def test_clean_names_and_covenant_labels(self):
        rows = {c["ticker"]: c
                for c in self.client.get("/companies").json()["companies"]}
        expected_names = {
            "SNBR": "Sleep Number", "GPK": "Graphic Packaging",
            "HAIN": "Hain Celestial", "NUVR": "Nuvera Communications",
            "STGW": "Stagwell", "AMCX": "AMC Networks",
            "ORLY": "O'Reilly Automotive", "QUAD": "Quad",
            "TRS": "TriMas", "AIN": "Albany International",
            "CRS": "Carpenter Technology", "OPTX": "Syntec Optics",
        }
        for ticker, name in expected_names.items():
            self.assertEqual(rows[ticker]["name"], name, ticker)
        allowed = {"Net leverage", "Total leverage", "Secured leverage",
                   "Interest coverage", "Fixed charge coverage",
                   "Debt service coverage"}
        for c in rows.values():
            if c["covenant"] is not None:
                self.assertIn(c["covenant"], allowed, c["ticker"])

    def test_snbr_row(self):
        rows = self.client.get("/companies").json()["companies"]
        snbr = next(c for c in rows if c["ticker"] == "SNBR")
        self.assertEqual(snbr["name"], "Sleep Number")
        self.assertEqual(snbr["period_end"], "2026-04-04")
        self.assertEqual(snbr["as_of"], "2026-04-04")
        self.assertEqual(snbr["covenant"], "Net leverage")
        self.assertEqual(snbr["ratio_with_savings"], 5.06)
        self.assertEqual(snbr["ratio_without_savings"], 6.58)
        self.assertEqual(snbr["ratio"], 6.58)
        self.assertEqual(snbr["threshold"], 4.75)
        self.assertAlmostEqual(snbr["headroom"], -1.83)
        self.assertEqual(snbr["status"], "fail")
        self.assertEqual(len(snbr["scenarios"]), 2)

    def test_failed_company_without_ratio(self):
        rows = self.client.get("/companies").json()["companies"]
        optx = next(c for c in rows if c["ticker"] == "OPTX")
        self.assertEqual(optx["status"], "fail")
        self.assertIsNone(optx["ratio"])
        self.assertIsNone(optx["headroom"])

    def test_no_paths_leak(self):
        text = self.client.get("/companies").text
        self.assertNotIn("/home/", text)
        self.assertNotIn("data/", text)
        self.assertNotIn("ONYA_", text)


class Periods(ApiTestBase):
    def test_periods(self):
        r = self.client.get("/company/SNBR/periods")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["ticker"], "SNBR")
        ends = [p["period_end"] for p in body["periods"]]
        self.assertEqual(ends, ["2025-09-27", "2026-01-03", "2026-04-04"])
        for p in body["periods"]:
            for cov in ("net_leverage", "interest_coverage"):
                for key in ("ratio", "threshold", "pass"):
                    self.assertIn(key, p[cov])

    def test_both_scenarios_where_present(self):
        periods = self.client.get("/company/SNBR/periods").json()["periods"]
        late = next(p for p in periods if p["period_end"] == "2026-04-04")
        self.assertEqual(len(late["scenarios"]), 2)
        self.assertEqual([s["savings"] for s in late["scenarios"]],
                         [0, 44000000])
        early = next(p for p in periods if p["period_end"] == "2025-09-27")
        self.assertIsNone(early["scenarios"])

    def test_unsupported_company(self):
        r = self.client.get("/company/GPK/periods")
        self.assertEqual(r.status_code, 404)


class PeriodDetail(ApiTestBase):
    def test_full_result_latest(self):
        r = self.client.get("/company/SNBR/period/2026-04-04")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["period_end"], "2026-04-04")
        self.assertTrue(body["components"])
        for comp in body["components"]:
            for key in ("name", "value", "source", "clause", "note"):
                self.assertIn(key, comp)
        self.assertEqual(body["flags"]["warning_count"], 2)
        self.assertEqual(
            {w["period_end"] for w in body["data_quality_warnings"]},
            {"2026-01-03"})
        self.assertEqual(body["covenant_clause"]["section"], "5.7(a)")
        self.assertEqual(body["covenant_clause"]["threshold"], 4.75)
        self.assertIn("4.75 to 1.00 for the Quarterly Reporting Period "
                      "ending April 4, 2026", body["covenant_clause"]["quote"])
        self.assertIn("4.80 to 1.00 for the Quarterly Reporting Period "
                      "ending July 4, 2026", body["covenant_clause"]["quote"])
        self.assertTrue(body["covenant_clause"]["quote"].endswith(
            "for each Quarterly Reporting Period occurring thereafter."))
        self.assertEqual(
            body["flags"]["reconciliation"],
            "not available (no company leverage table disclosed)")
        self.assertTrue(body["flags"]["unverifiable_proforma"])
        self.assertEqual(len(body["scenarios"]), 2)
        self.assertIn("base", body["cure"])
        self.assertIn("net_leverage", body["cure"]["base"])
        self.assertEqual(body["projection"]["next_test"], "2026-07-04")

    def test_reconciliation_and_no_projection(self):
        r = self.client.get("/company/SNBR/period/2025-09-27")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["reconciliation"]["status"], "reconciled")
        self.assertIsNone(body["projection"])
        self.assertFalse(body["flags"]["unverifiable_proforma"])

    def test_unknown_period(self):
        self.assertEqual(
            self.client.get("/company/SNBR/period/2000-01-01").status_code,
            404)
        self.assertEqual(
            self.client.get("/company/SNBR/period/nope").status_code, 404)
        self.assertEqual(
            self.client.get("/company/GPK/period/2026-04-04").status_code,
            404)

    def test_no_paths_leak(self):
        text = self.client.get("/company/SNBR/period/2026-04-04").text
        self.assertNotIn("/home/", text)
        self.assertNotIn(str(PROJECT_ROOT), text)


class Source(ApiTestBase):
    def test_contract_ref(self):
        r = self.client.get("/source",
                            params={"ref": "contract:(a)(iv)+(a)(viii)"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["kind"], "contract")
        self.assertEqual(len(body["clauses"]), 2)
        first = body["clauses"][0]
        self.assertEqual(first["clause_ref"], "(a)(iv)")
        self.assertEqual(first["section"], "1.1")
        self.assertIn("non-recurring", first["quote"])
        self.assertEqual(body["clauses"][1]["clause_ref"], "(a)(viii)")

    def test_contract_unknown_clause(self):
        r = self.client.get("/source", params={"ref": "contract:(z)(99)"})
        self.assertEqual(r.status_code, 404)

    def test_xbrl_ref_with_period(self):
        r = self.client.get(
            "/source",
            params={"ref": "xbrl:us-gaap:DebtCurrent",
                    "period_end": "2026-04-04"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["concept"], "us-gaap:DebtCurrent")
        self.assertEqual(body["label"], "Debt, Current")
        self.assertEqual(body["value"], 605600000)
        self.assertTrue(body["facts"])
        fact = body["facts"][0]
        self.assertEqual(fact["form"], "10-Q")
        self.assertEqual(fact["filed"], "2026-05-12")
        self.assertEqual(fact["val"], 605600000)

    def test_xbrl_ref_without_period(self):
        r = self.client.get("/source",
                            params={"ref": "xbrl:us-gaap:NetIncomeLoss"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsNone(body["value"])
        self.assertTrue(body["facts"])

    def test_xbrl_unknown_concept(self):
        r = self.client.get("/source",
                            params={"ref": "xbrl:us-gaap:NoSuchConcept"})
        self.assertEqual(r.status_code, 404)

    def test_release_ref_with_period(self):
        r = self.client.get(
            "/source",
            params={"ref": "release:Depreciation and amortization",
                    "period_end": "2026-04-04"})
        self.assertEqual(r.status_code, 200)
        matches = r.json()["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["quote"], "49,889")
        self.assertEqual(matches[0]["value_thousands"], 49889)

    def test_release_ref_all_periods(self):
        r = self.client.get(
            "/source",
            params={"ref": "release:Other non-recurring items"})
        self.assertEqual(r.status_code, 200)
        matches = r.json()["matches"]
        self.assertGreaterEqual(len(matches), 2)
        for m in matches:
            self.assertTrue(m["quote"])

    def test_release_unknown_line(self):
        r = self.client.get("/source",
                            params={"ref": "release:No such line"})
        self.assertEqual(r.status_code, 404)

    def test_unsupported_kind(self):
        r = self.client.get("/source",
                            params={"ref": "estimate:carried forward"})
        self.assertEqual(r.status_code, 400)

    def test_invalid_period(self):
        r = self.client.get(
            "/source",
            params={"ref": "xbrl:us-gaap:DebtCurrent",
                    "period_end": "yesterday"})
        self.assertEqual(r.status_code, 400)


class Backtest(ApiTestBase):
    def test_tables_and_totals(self):
        r = self.client.get("/backtest")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        disclosed = body["disclosed"]
        self.assertEqual(disclosed["totals"], {
            "covenants": 23, "actual_matched": 23,
            "threshold_matched": 23, "fully_matched": 23, "matched": 23,
            "verified": 22, "matched_and_verified": 22})
        self.assertEqual(len(disclosed["rows"]), 23)
        terms = body["terms"]
        self.assertEqual(terms["totals"], {
            "covenants": 16, "companies": 11, "matched": 12,
            "amended_after_agreement": 3, "no_disclosed_match": 0,
            "mismatched": 1, "quote_verified": 16})
        self.assertEqual(len(terms["rows"]), 16)
        self.assertEqual(len(terms["records"]), 11)


class AgentAuth(ApiTestBase):
    def test_missing_token(self):
        r = self.client.post("/agent/run", json={"question": "hi"})
        self.assertEqual(r.status_code, 401)

    def test_wrong_token(self):
        r = self.client.post("/agent/run", json={"question": "hi"},
                             headers={"X-Onya-Token": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_server_token_not_configured(self):
        os.environ.pop("ONYA_DEMO_TOKEN", None)
        r = self.client.post("/agent/run", json={"question": "hi"},
                             headers=self.auth())
        self.assertEqual(r.status_code, 500)

    def test_empty_question(self):
        r = self.client.post("/agent/run", json={"question": "  "},
                             headers=self.auth())
        self.assertEqual(r.status_code, 422)

    def test_question_too_long(self):
        r = self.client.post("/agent/run",
                             json={"question": "x" * 4001},
                             headers=self.auth())
        self.assertEqual(r.status_code, 413)


class AgentRun(ApiTestBase):
    def test_stream_steps_then_result(self):
        with patch.object(agent, "run_agent",
                          self.fake_run(answer="FINAL HERE", tokens=42)):
            r = self.client.post("/agent/run",
                                 json={"question": "Check SNBR?"},
                                 headers=self.auth())
        self.assertEqual(r.status_code, 200)
        self.assertIn("x-ndjson", r.headers["content-type"])
        events = _stream_events(r)
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["run_start", "tool_call", "run_result"])
        tool_step = events[1]
        self.assertEqual(tool_step["tool"], "lookup_company")
        self.assertEqual(tool_step["arguments"],
                         {"name_or_ticker": "SNBR"})
        result = events[-1]
        self.assertEqual(result["reason"], "done")
        self.assertEqual(result["answer"], "FINAL HERE")
        self.assertEqual(result["total_tokens"], 42)

    def test_replay_yields_incrementally(self):
        # One next() surfaces the first step with no waiting beyond it:
        # the replay streams as it goes instead of buffering the run.
        # (Each delay lands between two yields, never before the first.)
        sleeps = []
        store = limits.MemoryStore()
        gen = api._iter_replay(store)
        with patch("api.time.sleep",
                   side_effect=lambda s: sleeps.append(s)):
            first = next(gen)
            self.assertIn("step", first)
            self.assertEqual(sleeps, [])
            rest = list(gen)
        self.assertEqual(rest[-1]["type"], "run_result")
        steps = [e for e in [first, *rest]
                 if e.get("type") != "run_result"]
        self.assertGreater(len(steps), 1)
        self.assertEqual(len(sleeps), len(steps))

    def test_run_error_sanitized(self):
        def boom(question, run_id=None, **kwargs):
            raise RuntimeError(f"boom {PROJECT_ROOT}/x")

        with patch.object(agent, "run_agent", boom):
            r = self.client.post("/agent/run", json={"question": "q?"},
                                 headers=self.auth())
        events = _stream_events(r)
        errors = [e for e in events if e["type"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertNotIn(str(PROJECT_ROOT), errors[0]["error"])
        self.assertNotIn("/home/", json.dumps(events))

    def test_step_paths_redacted(self):
        def leaky(question, run_id=None, on_event=None, **kwargs):
            if on_event is not None:
                on_event(
                    {"run_id": run_id, "step": 1,
                     "timestamp": "2026-01-01T00:00:01+00:00",
                     "type": "tool_call", "tool": "extract_covenants",
                     "arguments": {"company": "SNBR"},
                     "result_summary": (
                         "reviewed file used: "
                         f"{PROJECT_ROOT}/data/extracted/x.json"),
                     "tokens": {"prompt": 0, "completion": 0, "total": 0},
                     "total_tokens": 0})
            return {"answer": "ok", "reason": "done", "run_id": run_id,
                    "tool_calls": 1, "total_tokens": 1, "figure_fields": []}

        with patch.object(agent, "run_agent", leaky):
            r = self.client.post("/agent/run", json={"question": "q?"},
                                 headers=self.auth())
        summary = _stream_events(r)[0]["result_summary"]
        self.assertNotIn(str(PROJECT_ROOT), summary)
        self.assertNotIn("/home/", summary)
        self.assertIn("[redacted]", summary)

    def test_polling_removed(self):
        r = self.client.get("/agent/run/0123456789ab")
        self.assertEqual(r.status_code, 404)
        self.assertIn("streams", r.json()["detail"])
        self.assertEqual(
            self.client.get("/agent/run/..%2F..%2Fx").status_code, 404)

    def test_periodless_question_replays_latest_computed(self):
        with patch.dict(os.environ, {"ONYA_AGENT_REPLAY": "1"}):
            with patch("api.time.sleep", return_value=None):
                r = self.client.post(
                    "/agent/run",
                    json={"question": "Check Sleep Number's covenants"},
                    headers=self.auth())
        events = _stream_events(r)
        result = events[-1]
        self.assertEqual(result["type"], "run_result")
        self.assertEqual(result["reason"], "replay")
        steps = [e for e in events if e.get("type") == "tool_call"]
        self.assertLessEqual(len(steps), 7)
        blob = json.dumps(events)
        self.assertIn("2026-04-04", blob)
        self.assertIn("FORBEARANCE", blob.upper())
        self.assertIn("THIRTEENTH", blob.upper())
        self.assertNotIn("FOURTEENTH", blob.upper())
        self.assertLessEqual(result["tool_calls"], 7)

    def test_replay_streams_sample(self):
        with patch.dict(os.environ, {"ONYA_AGENT_REPLAY": "1"}):
            with patch("api.time.sleep", return_value=None):
                r = self.client.post("/agent/run",
                                     json={"question": "Check SNBR?"},
                                     headers=self.auth())
        events = _stream_events(r)
        self.assertGreater(len(events), 2)
        self.assertEqual(events[-1]["type"], "run_result")
        self.assertEqual(events[-1]["reason"], "replay")
        self.assertTrue(events[-1]["answer"])
        kinds = {e["type"] for e in events[:-1]}
        self.assertIn("tool_call", kinds)


class AgentLimits(ApiTestBase):
    def test_five_per_hour_per_ip(self):
        with patch.object(agent, "run_agent", self.fake_run()):
            codes = [self.client.post(
                "/agent/run", json={"question": f"q{i}"},
                headers=self.auth()).status_code for i in range(6)]
        self.assertEqual(codes, [200, 200, 200, 200, 200, 429])

    def test_thirty_per_day_total(self):
        store = limits.local_store()
        for _ in range(30):
            store.claim(limits.day_key(), 2 * 86400)
        with patch.object(agent, "run_agent", self.fake_run()):
            r = self.client.post("/agent/run", json={"question": "q"},
                                 headers=self.auth())
        self.assertEqual(r.status_code, 429)

    def test_token_budget_reject(self):
        with patch.object(agent, "TOKEN_BUDGET", 100):
            with patch.object(agent, "run_agent", self.fake_run()):
                r = self.client.post("/agent/run",
                                     json={"question": "Check SNBR?"},
                                     headers=self.auth())
        self.assertEqual(r.status_code, 429)
        self.assertIn("token budget", r.json()["detail"])

    def test_fail_closed_without_redis_in_production(self):
        env = {"ONYA_ENV": "production"}
        for var in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
            env[var] = ""
        with patch.dict(os.environ, env, clear=False):
            with patch.object(agent, "run_agent", self.fake_run()):
                r = self.client.post("/agent/run",
                                     json={"question": "Check SNBR?"},
                                     headers=self.auth())
        self.assertEqual(r.status_code, 503)
        self.assertIn("paused", r.json()["detail"])


class FilingsSince(ApiTestBase):
    def test_snbr_filings_after_as_of(self):
        r = self.client.get(
            "/company/SNBR/filings-since?date=2026-05-19")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["cached"])
        self.assertTrue(body["filings"])
        for row in body["filings"]:
            self.assertIn(row["form"], ("10-K", "10-Q", "8-K"))
            self.assertGreater(row["filingDate"], "2026-05-19")
            self.assertTrue(
                row["sec_url"].startswith(
                    "https://www.sec.gov/Archives/edgar/data/827187/"))
        dates = [row["filingDate"] for row in body["filings"]]
        self.assertTrue(any(d.startswith("2026-06") for d in dates),
                        dates)

    def test_no_live_call_in_request_path(self):
        import edgar

        def dead(*args, **kwargs):
            raise AssertionError("network call attempted")

        with patch.object(edgar.requests, "get", side_effect=dead), \
             patch.object(edgar.requests, "post", side_effect=dead), \
             patch.object(edgar, "fetch", side_effect=dead):
            r = self.client.get(
                "/company/SNBR/filings-since?date=2026-05-19")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["cached"])

    def test_missing_cache_says_so(self):
        with patch("edgar.filings_since", return_value=None):
            r = self.client.get(
                "/company/SNBR/filings-since?date=2026-05-19")
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(body["cached"])
        self.assertEqual(body["filings"], [])
        self.assertIn("note", body)

    def test_bad_date_and_unknown_company(self):
        r = self.client.get("/company/SNBR/filings-since?date=May")
        self.assertEqual(r.status_code, 422)
        r = self.client.get("/company/ZZZ/filings-since?date=2026-05-19")
        self.assertEqual(r.status_code, 404)


class InfoRequestEndpoint(ApiTestBase):
    def test_streams_request(self):
        r = self.client.post("/agent/info-request",
                             json={"company": "SNBR",
                                   "period_end": "2026-04-04"},
                             headers=self.auth())
        self.assertEqual(r.status_code, 200)
        events = _stream_events(r)
        self.assertEqual(events[0]["type"], "tool_call")
        self.assertEqual(events[0]["tool"], "draft_info_request")
        result = events[-1]
        self.assertEqual(result["type"], "run_result")
        self.assertEqual(result["reason"], "info_request")
        text = result["info_request"]
        self.assertIn("FORBEARANCE", text.upper())
        self.assertIn("[lender to fill]", text)
        self.assertNotIn("FOURTEENTH", text.upper())

    def test_counts_toward_limits(self):
        with patch.object(limits, "MAX_RUNS_PER_HOUR_PER_IP", 0):
            r = self.client.post("/agent/info-request",
                                 json={"company": "SNBR",
                                       "period_end": "2026-04-04"},
                                 headers=self.auth())
        self.assertEqual(r.status_code, 429)

    def test_auth_and_validation(self):
        r = self.client.post("/agent/info-request",
                             json={"company": "SNBR",
                                   "period_end": "2026-04-04"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/agent/info-request",
                             json={"company": "SNBR"},
                             headers=self.auth())
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/agent/info-request",
                             json={"company": "SNBR",
                                   "period_end": "April"},
                             headers=self.auth())
        self.assertEqual(r.status_code, 422)


class ReplayFlag(unittest.TestCase):
    def test_replay_defaults_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ONYA_AGENT_REPLAY", None)
            self.assertFalse(api._agent_replay_enabled())
        with patch.dict(os.environ, {"ONYA_AGENT_REPLAY": "1"}):
            self.assertTrue(api._agent_replay_enabled())
        with patch.dict(os.environ, {"ONYA_AGENT_REPLAY": "true"}):
            self.assertFalse(api._agent_replay_enabled())


class ProductionGuards(ApiTestBase):
    PROD = {"ONYA_ENV": "production",
            "ONYA_DEMO_TOKEN": "prod-token",
            "ONYA_FRONTEND_ORIGIN": "https://onya.example.app"}

    def test_production_replay_refused(self):
        with patch.dict(os.environ, {**self.PROD, "ONYA_AGENT_REPLAY": "0"}):
            with self.assertRaises(RuntimeError):
                api.create_app()

    def test_production_missing_token_refused(self):
        env = {k: v for k, v in self.PROD.items() if k != "ONYA_DEMO_TOKEN"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("ONYA_DEMO_TOKEN", None)
            with self.assertRaises(RuntimeError):
                api.create_app()

    def test_production_missing_origin_refused(self):
        env = {k: v for k, v in self.PROD.items()
               if k != "ONYA_FRONTEND_ORIGIN"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("ONYA_FRONTEND_ORIGIN", None)
            with self.assertRaises(RuntimeError):
                api.create_app()

    def test_production_cors_only_frontend_origin(self):
        with patch.dict(os.environ, self.PROD):
            app = api.create_app()
            client = TestClient(app)
            r = client.get("/health",
                           headers={"Origin": "http://localhost:3000"})
            self.assertIsNone(r.headers.get("access-control-allow-origin"))
            r = client.get(
                "/health",
                headers={"Origin": "https://onya.example.app"})
            self.assertEqual(r.headers.get("access-control-allow-origin"),
                             "https://onya.example.app")

    def test_kill_switch(self):
        with patch.dict(os.environ, {"ONYA_AGENT_ENABLED": "0"}):
            with patch.object(agent, "run_agent", self.fake_run()):
                r = self.client.post("/agent/run",
                                     json={"question": "Check SNBR?"},
                                     headers=self.auth())
        self.assertEqual(r.status_code, 503)
        self.assertIn("paused", r.json()["detail"])

    def test_daily_token_budget(self):
        with patch.dict(os.environ, {"ONYA_DAILY_TOKEN_BUDGET": "10"}):
            with patch.object(agent, "run_agent",
                              self.fake_run(tokens=100)):
                r = self.client.post("/agent/run",
                                     json={"question": "Check SNBR?"},
                                     headers=self.auth())
                self.assertEqual(r.status_code, 200)
                result = _stream_events(r)[-1]
                self.assertEqual(result["type"], "run_result")
                r2 = self.client.post("/agent/run",
                                      json={"question": "Check SNBR?"},
                                      headers=self.auth())
        self.assertEqual(r2.status_code, 429)
        self.assertIn("budget", r2.json()["detail"].lower())

    def test_forwarded_ip_trusted_only_with_token(self):
        with patch.object(agent, "run_agent", self.fake_run()):
            for _ in range(5):
                r = self.client.post(
                    "/agent/run", json={"question": "Check SNBR?"},
                    headers={**self.auth(),
                             "X-Onya-Client-IP": "203.0.113.9"})
                self.assertEqual(r.status_code, 200)
            sixth = self.client.post(
                "/agent/run", json={"question": "Check SNBR?"},
                headers={**self.auth(), "X-Onya-Client-IP": "203.0.113.9"})
            self.assertEqual(sixth.status_code, 429)
            other = self.client.post(
                "/agent/run", json={"question": "Check SNBR?"},
                headers={**self.auth(), "X-Onya-Client-IP": "203.0.113.10"})
            self.assertEqual(other.status_code, 200)

    def test_forwarded_ip_ignored_without_valid_token(self):
        r = self.client.post(
            "/agent/run", json={"question": "Check SNBR?"},
            headers={"X-Onya-Token": "wrong",
                     "X-Onya-Client-IP": "203.0.113.9"})
        self.assertEqual(r.status_code, 401)


class Cors(ApiTestBase):
    def test_allowed_origin(self):
        r = self.client.get("/health",
                            headers={"Origin": "http://localhost:3000"})
        self.assertEqual(r.headers.get("access-control-allow-origin"),
                         "http://localhost:3000")

    def test_disallowed_origin(self):
        r = self.client.get("/health",
                            headers={"Origin": "http://evil.example"})
        self.assertIsNone(r.headers.get("access-control-allow-origin"))

    def test_extra_origin_from_env(self):
        os.environ["ONYA_FRONTEND_ORIGIN"] = "https://demo.example"
        try:
            app = api.create_app()
        finally:
            os.environ.pop("ONYA_FRONTEND_ORIGIN", None)
        client = TestClient(app)
        r = client.get("/health",
                       headers={"Origin": "https://demo.example"})
        self.assertEqual(r.headers.get("access-control-allow-origin"),
                         "https://demo.example")


if __name__ == "__main__":
    unittest.main()
