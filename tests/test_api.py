"""Tests for src/api.py (FastAPI TestClient; agent runs mocked)."""

import json
import os
import sys
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import agent  # noqa: E402
import api  # noqa: E402

TOKEN = "test-token-123"

TICKERS = {"TRS", "AIN", "AMCX", "STGW", "QUAD", "CRS", "ORLY", "GPK",
           "NUVR", "HAIN", "SNBR", "OPTX"}


def _trace_path(run_id):
    return PROJECT_ROOT / "data" / "runs" / f"{run_id}.jsonl"


def _poll_done(client, run_id, timeout=10):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/agent/run/{run_id}")
        if last.status_code == 200 and last.json()["status"] != "running":
            return last
        time.sleep(0.05)
    return last


class ApiTestBase(unittest.TestCase):
    def setUp(self):
        self._old_token = os.environ.get("ONYA_DEMO_TOKEN")
        os.environ["ONYA_DEMO_TOKEN"] = TOKEN
        api._reset_state()
        self.client = TestClient(api.app)
        self._traces = []

    def tearDown(self):
        if self._old_token is None:
            os.environ.pop("ONYA_DEMO_TOKEN", None)
        else:
            os.environ["ONYA_DEMO_TOKEN"] = self._old_token
        api._reset_state()
        for run_id in self._traces:
            try:
                _trace_path(run_id).unlink()
            except OSError:
                pass

    def auth(self):
        return {"X-Onya-Token": TOKEN}

    def fake_run(self, answer="CANNED ANSWER", tokens=100, tool_calls=1,
                 with_trace=True):
        def _fake(question, run_id=None, **kwargs):
            if with_trace:
                agent.log_step(
                    _trace_path(run_id),
                    {"run_id": run_id, "step": 0,
                     "timestamp": "2026-01-01T00:00:00+00:00",
                     "type": "run_start", "tool": None, "arguments": {},
                     "result_summary": question[:300],
                     "tokens": {"prompt": 0, "completion": 0, "total": 0},
                     "total_tokens": 0})
                agent.log_step(
                    _trace_path(run_id),
                    {"run_id": run_id, "step": 1,
                     "timestamp": "2026-01-01T00:00:01+00:00",
                     "type": "tool_call", "tool": "lookup_company",
                     "arguments": {"name_or_ticker": "SNBR"},
                     "result_summary": "SNBR: 1 candidate(s)",
                     "tokens": {"prompt": 10, "completion": 5, "total": 15},
                     "total_tokens": 15})
                agent.log_step(
                    _trace_path(run_id),
                    {"run_id": run_id, "step": 2,
                     "timestamp": "2026-01-01T00:00:02+00:00",
                     "type": "run_end", "tool": None, "arguments": {},
                     "result_summary": "done",
                     "tokens": {"prompt": 0, "completion": 0, "total": 0},
                     "total_tokens": tokens, "reason": "done"})
            return {"answer": answer, "reason": "done", "run_id": run_id,
                    "tool_calls": tool_calls, "total_tokens": tokens,
                    "trace_path": str(_trace_path(run_id))}
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
    def test_run_returns_immediately_then_done(self):
        started = threading.Event()
        release = threading.Event()

        def slow(question, run_id=None, **kwargs):
            started.set()
            release.wait(10)
            return {"answer": "SLOW ANSWER", "reason": "done",
                    "run_id": run_id, "tool_calls": 0, "total_tokens": 7,
                    "trace_path": "none"}

        with patch.object(agent, "run_agent", slow):
            r = self.client.post("/agent/run",
                                 json={"question": "Check SNBR?"},
                                 headers=self.auth())
            self.assertEqual(r.status_code, 202)
            run_id = r.json()["run_id"]
            self.assertEqual(r.json()["status"], "running")
            self.assertTrue(started.wait(5))
            # Returns while the worker is still blocked: polled state.
            mid = self.client.get(f"/agent/run/{run_id}")
            self.assertEqual(mid.json()["status"], "running")
            self.assertIsNone(mid.json()["answer"])
            release.set()
            done = _poll_done(self.client, run_id)
        self.assertEqual(done.json()["status"], "done")
        self.assertEqual(done.json()["answer"], "SLOW ANSWER")
        self.assertEqual(done.json()["total_tokens"], 7)

    def test_trace_steps_and_answer(self):
        with patch.object(agent, "run_agent",
                          self.fake_run(answer="FINAL HERE", tokens=42)):
            r = self.client.post("/agent/run",
                                 json={"question": "Check SNBR?"},
                                 headers=self.auth())
            run_id = r.json()["run_id"]
            self._traces.append(run_id)
            done = _poll_done(self.client, run_id)
        body = done.json()
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["answer"], "FINAL HERE")
        self.assertEqual(body["total_tokens"], 42)
        kinds = [s["type"] for s in body["steps"]]
        self.assertEqual(kinds, ["run_start", "tool_call", "run_end"])
        tool_step = body["steps"][1]
        self.assertEqual(tool_step["tool"], "lookup_company")
        self.assertEqual(tool_step["arguments"],
                         {"name_or_ticker": "SNBR"})

    def test_run_error_sanitized(self):
        def boom(question, run_id=None, **kwargs):
            raise RuntimeError(f"boom {PROJECT_ROOT}/x")

        with patch.object(agent, "run_agent", boom):
            r = self.client.post("/agent/run", json={"question": "q?"},
                                 headers=self.auth())
            run_id = r.json()["run_id"]
            done = _poll_done(self.client, run_id)
        body = done.json()
        self.assertEqual(body["status"], "failed")
        self.assertNotIn(str(PROJECT_ROOT), body["error"])
        self.assertNotIn("/home/", json.dumps(body))
        self.assertTrue(
            any(s["type"] == "error" for s in body["steps"]),
            body["steps"])

    def test_unknown_run(self):
        self.assertEqual(
            self.client.get("/agent/run/0123456789ab").status_code, 404)
        self.assertEqual(
            self.client.get("/agent/run/..%2F..%2Fx").status_code, 404)

    def test_preexisting_trace_without_record(self):
        run_id = "deadbeef1234"
        self._traces.append(run_id)
        agent.log_step(_trace_path(run_id),
                       {"run_id": run_id, "step": 0,
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "type": "run_start", "tool": None, "arguments": {},
                        "result_summary": "old CLI run",
                        "tokens": {"prompt": 1, "completion": 1, "total": 2},
                        "total_tokens": 2})
        r = self.client.get(f"/agent/run/{run_id}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["steps"]), 1)
        self.assertIsNone(body["answer"])

    def test_trace_paths_redacted(self):
        run_id = "abc123abc123"
        self._traces.append(run_id)
        agent.log_step(
            _trace_path(run_id),
            {"run_id": run_id, "step": 1,
             "timestamp": "2026-01-01T00:00:01+00:00",
             "type": "tool_call", "tool": "extract_covenants",
             "arguments": {"company": "SNBR"},
             "result_summary":
                 f"reviewed file used: {PROJECT_ROOT}/data/extracted/x.json",
             "tokens": {"prompt": 0, "completion": 0, "total": 0},
             "total_tokens": 0})
        body = self.client.get(f"/agent/run/{run_id}").json()
        summary = body["steps"][0]["result_summary"]
        self.assertNotIn(str(PROJECT_ROOT), summary)
        self.assertNotIn("/home/", summary)
        self.assertIn("[redacted]", summary)


class AgentLimits(ApiTestBase):
    def test_five_per_hour_per_ip(self):
        with patch.object(agent, "run_agent",
                          self.fake_run(with_trace=False)):
            codes = [self.client.post(
                "/agent/run", json={"question": f"q{i}"},
                headers=self.auth()).status_code for i in range(6)]
        self.assertEqual(codes, [202, 202, 202, 202, 202, 429])

    def test_thirty_per_day_total(self):
        now = datetime.now(timezone.utc)
        with api._LOCK:
            api._RUN_STARTS.extend([now] * 30)
        with patch.object(agent, "run_agent",
                          self.fake_run(with_trace=False)):
            r = self.client.post("/agent/run", json={"question": "q"},
                                 headers=self.auth())
        self.assertEqual(r.status_code, 429)

    def test_token_budget_reject(self):
        with patch.object(agent, "TOKEN_BUDGET", 100):
            with patch.object(agent, "run_agent",
                              self.fake_run(with_trace=False)):
                r = self.client.post("/agent/run",
                                     json={"question": "Check SNBR?"},
                                     headers=self.auth())
        self.assertEqual(r.status_code, 429)
        self.assertIn("token budget", r.json()["detail"])


class ReplayFlag(unittest.TestCase):
    def test_replay_defaults_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ONYA_AGENT_REPLAY", None)
            self.assertFalse(api._agent_replay_enabled())
        with patch.dict(os.environ, {"ONYA_AGENT_REPLAY": "1"}):
            self.assertTrue(api._agent_replay_enabled())
        with patch.dict(os.environ, {"ONYA_AGENT_REPLAY": "true"}):
            self.assertFalse(api._agent_replay_enabled())


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
