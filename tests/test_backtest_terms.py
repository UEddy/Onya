"""Focused tests for src/backtest_terms.py (mocked model/EDGAR; no live calls)."""

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

import backtest_terms
import extract
import extract_disclosed
from openai import APIConnectionError


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
    "CREDIT AGREEMENT dated as of May 1, 2025.\n"
    "Section 7.11 Total Net Leverage Ratio shall not exceed 4.00 to 1.00.\n"
    "Section 7.12 Interest Expense Coverage Ratio shall not be less "
    "than 3.00 to 1.00.\n"
)

PARSED = {
    "borrower": "Test Corp",
    "agreement": {"title": "Credit Agreement", "dated": "2025-05-01",
                 "administrative_agent": "Bank"},
    "financial_covenants": [
        {"id": "lev",
         "name": "Total Net Leverage Ratio",
         "section": "7.11",
         "direction": "max",
         "metric_term": "Total Net Leverage Ratio",
         "unit": "ratio",
         "thresholds": [{"period_end": "2025-09-30", "applies_after": None,
                         "value": 4.0, "condition": None}],
         "quote": "Total Net Leverage Ratio shall not exceed 4.00 to 1.00."},
        {"id": "cov",
         "name": "Interest Expense Coverage Ratio",
         "section": "7.12",
         "direction": "min",
         "metric_term": "Interest Expense Coverage Ratio",
         "unit": "ratio",
         "thresholds": [{"period_end": "2025-09-30", "applies_after": None,
                         "value": 3.0, "condition": None}],
         "quote": "Interest Expense Coverage Ratio shall not be less "
                  "than 3.00 to 1.00."},
    ],
    "cap_groups": [],
    "definitions": [],
    "specified_defaults": [],
    "equity_cure": {"present": False, "section": None, "max_uses": None,
                    "limits": None, "how_applied": None, "quote": None},
    "uncertainties": [],
}

DISCLOSED = {
    "period_end": "2025-09-30",
    "covenants": [
        {"name": "total net leverage",
         "direction": "max",
         "threshold": 4.0,
         "actual": 2.29,
         "in_compliance": True,
         "waiver_or_amendment_note": None,
         "quote": "q"},
        {"name": "interest expense coverage",
         "direction": "min",
         "threshold": 3.0,
         "actual": 10.46,
         "in_compliance": True,
         "waiver_or_amendment_note": None,
         "quote": "q"},
    ],
}

BASE = {"url": "https://www.sec.gov/Archives/edgar/data/842633/"
               "000084263325000073/ex101creditagreement.htm",
        "filingDate": "2025-05-06",
        "form": "8-K"}


def _case(ticker="TST", period_end="2025-09-30"):
    return {"ticker": ticker, "period_end": period_end,
            "filing_url": "https://www.sec.gov/Archives/edgar/data/1/x.htm"}


class ModelConfig(unittest.TestCase):
    def test_baseten_model_and_params(self):
        self.assertEqual(backtest_terms.MODEL,
                         "meta-models/muse-spark-open-1026")
        self.assertEqual(backtest_terms.TEMPERATURE, 0)
        self.assertEqual(backtest_terms.MAX_TOKENS, 32000)

    def test_make_client_uses_baseten_env(self):
        with (patch.dict("os.environ",
                         {"BASETEN_API_KEY": "k", "BASETEN_BASE_URL": "u"}),
              patch.object(backtest_terms, "OpenAI") as factory):
            backtest_terms.make_client()
        factory.assert_called_once_with(api_key="k", base_url="u")

    def test_reuses_extract_logic(self):
        self.assertIs(backtest_terms.INSTRUCTIONS, extract.INSTRUCTIONS)
        self.assertIs(backtest_terms.SCHEMA, extract.SCHEMA)

    def test_never_reads_answer_key(self):
        source = Path(backtest_terms.__file__).read_text(encoding="utf-8")
        code = source.replace(backtest_terms.__doc__ or "", "", 1)
        self.assertNotIn("answer_key", code)


class SelectionInputs(unittest.TestCase):
    def test_as_of_is_period_end_plus_45_days(self):
        self.assertEqual(backtest_terms.as_of_for("2025-09-30"),
                         "2025-11-14")

    def test_company_key_prefers_cik(self):
        self.assertEqual(
            backtest_terms.company_key({"ticker": "X", "cik": "123"}), "123")
        self.assertEqual(
            backtest_terms.company_key({"ticker": "X"}), "X")

    def test_agreement_cache_filename_reuses_edgar_name(self):
        name = backtest_terms.agreement_cache_filename("TRS", BASE["url"])
        self.assertEqual(name, "842633_000084263325000073_"
                              "ex101creditagreement.htm")

    def test_agreement_cache_filename_fallback(self):
        name = backtest_terms.agreement_cache_filename(
            "TST", "https://example.invalid/files/agreement.htm")
        self.assertEqual(name, "backtest_terms_TST_agreement.htm")


class BuildContent(unittest.TestCase):
    def test_document_first_instructions_second(self):
        content = backtest_terms.build_content("DOC")
        self.assertTrue(content.startswith("DOC\n\n---\n\n"))
        self.assertIn(extract.INSTRUCTIONS, content)


class ParseResponse(unittest.TestCase):
    def test_retry_once_on_invalid_json(self):
        client = FakeClient([_response("not json"),
                             _response(json.dumps(PARSED))])
        parsed, _, _ = backtest_terms.parse_response(client, "content")
        self.assertEqual(parsed["borrower"], "Test Corp")
        self.assertEqual(len(client.chat.completions.requests), 2)

    def test_request_uses_model_params(self):
        client = FakeClient([_response(json.dumps(PARSED))])
        backtest_terms.parse_response(client, "content")
        kwargs = client.chat.completions.requests[0]
        self.assertEqual(kwargs["model"], "meta-models/muse-spark-open-1026")
        self.assertEqual(kwargs["temperature"], 0)
        self.assertEqual(kwargs["max_tokens"], 32000)


class RequestRetry(unittest.TestCase):
    def _failing_client(self, failures, response):
        client = FakeClient([])
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) <= failures:
                raise APIConnectionError(request=None)
            return response

        client.chat.completions.create = create
        return client, calls

    def test_connection_error_retries_then_raises(self):
        client, calls = self._failing_client(99, None)
        with patch.object(backtest_terms.time, "sleep") as sleep:
            with self.assertRaises(APIConnectionError):
                backtest_terms.request_completion(client, "content")
        self.assertEqual(len(calls), 4)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],
                         [5, 15, 30])

    def test_recovers_after_transient_failures(self):
        resp = _response(json.dumps(PARSED))
        client, calls = self._failing_client(2, resp)
        with patch.object(backtest_terms.time, "sleep") as sleep:
            self.assertIs(
                backtest_terms.request_completion(client, "content"), resp)
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 15])


class VerifyQuotes(unittest.TestCase):
    def test_all_verified(self):
        verified, total, failures, flags = backtest_terms.verify_quotes(
            PARSED, DOCUMENT)
        self.assertEqual(failures, [])
        self.assertEqual(verified, total)
        self.assertGreater(total, 0)
        self.assertEqual(flags, [True, True])

    def test_bad_quote_fails(self):
        bad = json.loads(json.dumps(PARSED))
        bad["financial_covenants"][0]["quote"] = "not in the document"
        verified, total, failures, flags = backtest_terms.verify_quotes(
            bad, DOCUMENT)
        self.assertEqual(len(failures), 1)
        self.assertEqual(verified, total - 1)
        self.assertEqual(flags, [False, True])


class ApplicableThreshold(unittest.TestCase):
    def test_exact_match(self):
        sched = [{"period_end": "2025-06-30", "applies_after": None,
                  "value": 4.5, "condition": None},
                 {"period_end": "2025-09-30", "applies_after": None,
                  "value": 4.0, "condition": None}]
        self.assertEqual(
            backtest_terms.applicable_threshold(sched, "2025-09-30"), 4.0)
        self.assertEqual(
            backtest_terms.applicable_threshold(sched, "2025-06-30"), 4.5)

    def test_thereafter_applies_past_last_dated(self):
        sched = [{"period_end": "2025-06-30", "applies_after": None,
                  "value": 5.0, "condition": None},
                 {"period_end": None, "applies_after": "2025-06-30",
                  "value": 5.5, "condition": None}]
        self.assertEqual(
            backtest_terms.applicable_threshold(sched, "2025-09-30"), 5.5)
        self.assertEqual(
            backtest_terms.applicable_threshold(sched, "2025-06-30"), 5.0)

    def test_latest_before_when_between_entries(self):
        sched = [{"period_end": "2025-03-31", "applies_after": None,
                  "value": 5.0, "condition": None},
                 {"period_end": "2025-09-30", "applies_after": None,
                  "value": 4.0, "condition": None}]
        self.assertEqual(
            backtest_terms.applicable_threshold(sched, "2025-06-30"), 5.0)

    def test_earliest_when_before_schedule(self):
        sched = [{"period_end": "2025-06-30", "applies_after": None,
                  "value": 5.0, "condition": None}]
        self.assertEqual(
            backtest_terms.applicable_threshold(sched, "2025-03-31"), 5.0)

    def test_empty_schedule_is_none(self):
        self.assertIsNone(backtest_terms.applicable_threshold([], "2025-09-30"))
        self.assertIsNone(
            backtest_terms.applicable_threshold(None, "2025-09-30"))

    def test_conditional_entry_never_wins_by_default(self):
        # Real TRS shape: base 4.0 plus a covenant-holiday 4.5.
        sched = [{"period_end": None, "applies_after": "2024-12-31",
                  "value": 4.0, "condition": None},
                 {"period_end": None, "applies_after": "2024-12-31",
                  "value": 4.5,
                  "condition": "during a Covenant Holiday Period"}]
        self.assertEqual(
            backtest_terms.applicable_threshold(sched, "2025-09-30"), 4.0)

    def test_unconditional_wins_over_conditional_exact_date(self):
        sched = [{"period_end": "2025-09-30", "applies_after": None,
                  "value": 4.5, "condition": "during a Covenant Holiday Period"},
                 {"period_end": None, "applies_after": "2024-12-31",
                  "value": 4.0, "condition": None}]
        self.assertEqual(
            backtest_terms.applicable_threshold(sched, "2025-09-30"), 4.0)

    def test_all_conditional_returns_none(self):
        sched = [{"period_end": "2025-09-30", "applies_after": None,
                  "value": 4.5, "condition": "during a Covenant Holiday Period"}]
        self.assertIsNone(
            backtest_terms.applicable_threshold(sched, "2025-09-30"))


TRS_SCHEDULE = [
    {"period_end": None, "applies_after": "2024-12-31",
     "value": 4.0, "condition": None},
    {"period_end": None, "applies_after": "2024-12-31",
     "value": 4.5, "condition": "during a Covenant Holiday Period"},
]

TRS_HOLIDAY_NOTE = (
    "If acquisition qualifies for Covenant Holiday Period, permitted "
    "ratio cannot exceed 4.50 to 1.00 during that period")


class ConditionalAlternatives(unittest.TestCase):
    def test_trs_holiday_reported_with_condition(self):
        self.assertEqual(
            backtest_terms.conditional_alternatives(
                TRS_SCHEDULE, "2025-09-30"),
            [{"value": 4.5,
              "condition": "during a Covenant Holiday Period"}])

    def test_no_conditionals_is_empty(self):
        sched = [{"period_end": "2025-09-30", "applies_after": None,
                  "value": 4.0, "condition": None}]
        self.assertEqual(
            backtest_terms.conditional_alternatives(sched, "2025-09-30"),
            [])

    def test_empty_schedule_is_empty(self):
        self.assertEqual(
            backtest_terms.conditional_alternatives([], "2025-09-30"), [])
        self.assertEqual(
            backtest_terms.conditional_alternatives(None, "2025-09-30"), [])


class ConditionActive(unittest.TestCase):
    CONDITION = "during a Covenant Holiday Period"

    def test_hypothetical_note_with_base_threshold_is_inactive(self):
        dis = {"threshold": 4.0,
               "waiver_or_amendment_note": TRS_HOLIDAY_NOTE}
        self.assertFalse(
            backtest_terms.condition_active(self.CONDITION, 4.5, dis))

    def test_active_condition_with_matching_threshold(self):
        dis = {"threshold": 4.5,
               "waiver_or_amendment_note":
                   "Covenant Holiday Period in effect following "
                   "acquisition; permitted ratio 4.50"}
        self.assertTrue(
            backtest_terms.condition_active(self.CONDITION, 4.5, dis))

    def test_matching_threshold_without_note_is_inactive(self):
        dis = {"threshold": 4.5, "waiver_or_amendment_note": None}
        self.assertFalse(
            backtest_terms.condition_active(self.CONDITION, 4.5, dis))

    def test_active_note_with_base_threshold_is_inactive(self):
        dis = {"threshold": 4.0,
               "waiver_or_amendment_note":
                   "Covenant Holiday Period in effect"}
        self.assertFalse(
            backtest_terms.condition_active(self.CONDITION, 4.5, dis))

    def test_missing_disclosure_or_condition_is_inactive(self):
        dis = {"threshold": 4.5,
               "waiver_or_amendment_note": "Covenant Holiday Period"}
        self.assertFalse(
            backtest_terms.condition_active(self.CONDITION, 4.5, None))
        self.assertFalse(backtest_terms.condition_active("", 4.5, dis))
        self.assertFalse(backtest_terms.condition_active(None, 4.5, dis))


class DisclosureCitesAmendment(unittest.TestCase):
    def test_amendment_and_waiver_notes(self):
        self.assertTrue(backtest_terms.disclosure_cites_amendment(
            {"waiver_or_amendment_note": "Amended via Fourth Amendment"}))
        self.assertTrue(backtest_terms.disclosure_cites_amendment(
            {"waiver_or_amendment_note": "waiver to 1.75 on August 6, 2026"}))

    def test_missing_or_unrelated_note(self):
        self.assertFalse(backtest_terms.disclosure_cites_amendment(
            {"waiver_or_amendment_note": None}))
        self.assertFalse(backtest_terms.disclosure_cites_amendment({}))
        self.assertFalse(backtest_terms.disclosure_cites_amendment(
            {"waiver_or_amendment_note": "Covenant Holiday Period to 4.50"}))


class ScoreTerms(unittest.TestCase):
    def test_match_within_tolerance(self):
        agr = [{"name": "Total Net Leverage Ratio", "direction": "max",
                "thresholds": [{"period_end": "2025-09-30",
                                "applies_after": None, "value": 4.0,
                                "condition": None}]}]
        dis = [{"name": "total net leverage", "direction": "max",
                "threshold": 4.0, "waiver_or_amendment_note": None}]
        rows, extras = backtest_terms.score_terms(
            "TST", "2025-09-30", agr, dis, "http://u", [True])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["match"])
        self.assertEqual(row["status"], backtest_terms.ROW_MATCH)
        self.assertEqual(row["agreement_threshold"], 4.0)
        self.assertEqual(row["disclosed_threshold"], 4.0)
        self.assertTrue(row["quote_verified"])
        self.assertEqual(row["agreement_url"], "http://u")
        self.assertEqual(extras, [])

    def test_tolerance_boundary(self):
        agr = [{"name": "leverage", "direction": "max",
                "thresholds": [{"period_end": "2025-09-30",
                                "applies_after": None, "value": 2.29,
                                "condition": None}]}]
        close = [{"name": "leverage", "direction": "max", "threshold": 2.30,
                  "waiver_or_amendment_note": None}]
        rows, _ = backtest_terms.score_terms(
            "TST", "2025-09-30", agr, close, "http://u", [True])
        self.assertTrue(rows[0]["match"])
        far = [{"name": "leverage", "direction": "max", "threshold": 2.31,
                "waiver_or_amendment_note": None}]
        rows, _ = backtest_terms.score_terms(
            "TST", "2025-09-30", agr, far, "http://u", [True])
        self.assertFalse(rows[0]["match"])
        self.assertEqual(rows[0]["status"], backtest_terms.ROW_MISMATCH)

    def test_direction_must_agree(self):
        agr = [{"name": "leverage", "direction": "min",
                "thresholds": [{"period_end": "2025-09-30",
                                "applies_after": None, "value": 3.0,
                                "condition": None}]}]
        dis = [{"name": "leverage", "direction": "max", "threshold": 3.0,
                "waiver_or_amendment_note": None}]
        rows, extras = backtest_terms.score_terms(
            "TST", "2025-09-30", agr, dis, "http://u", [True])
        self.assertEqual(rows[0]["status"], backtest_terms.ROW_NO_DISCLOSED)
        self.assertIsNone(rows[0]["disclosed_threshold"])
        self.assertEqual(extras, ["leverage"])

    def test_amended_after_agreement_not_a_miss(self):
        agr = [{"name": "consolidated secured leverage ratio",
                "direction": "max",
                "thresholds": [{"period_end": "2025-09-30",
                                "applies_after": None, "value": 5.0,
                                "condition": None}]}]
        dis = [{"name": "consolidated secured leverage ratio",
                "direction": "max", "threshold": 5.5,
                "waiver_or_amendment_note": "Amended via Fourth Amendment"}]
        rows, _ = backtest_terms.score_terms(
            "HAIN", "2025-09-30", agr, dis, "http://u", [True])
        self.assertFalse(rows[0]["match"])
        self.assertEqual(rows[0]["status"], backtest_terms.ROW_AMENDED)

    def test_conditional_prefers_base_and_reports_alternative(self):
        agr = [{"name": "Total Net Leverage Ratio", "direction": "max",
                "thresholds": TRS_SCHEDULE}]
        dis = [{"name": "total net leverage", "direction": "max",
                "threshold": 4.0,
                "waiver_or_amendment_note": TRS_HOLIDAY_NOTE}]
        rows, _ = backtest_terms.score_terms(
            "TRS", "2025-09-30", agr, dis, "http://u", [True])
        row = rows[0]
        self.assertEqual(row["agreement_threshold"], 4.0)
        self.assertTrue(row["match"])
        self.assertEqual(row["status"], backtest_terms.ROW_MATCH)
        self.assertEqual(row["conditional_alternatives"],
                         [{"value": 4.5,
                           "condition": "during a Covenant Holiday Period"}])

    def test_active_condition_uses_alternative(self):
        agr = [{"name": "Total Net Leverage Ratio", "direction": "max",
                "thresholds": TRS_SCHEDULE}]
        dis = [{"name": "total net leverage", "direction": "max",
                "threshold": 4.5,
                "waiver_or_amendment_note":
                    "Covenant Holiday Period in effect following "
                    "acquisition"}]
        rows, _ = backtest_terms.score_terms(
            "TRS", "2025-09-30", agr, dis, "http://u", [True])
        row = rows[0]
        self.assertEqual(row["agreement_threshold"], 4.5)
        self.assertTrue(row["match"])

    def test_row_records_repaired_flag(self):
        agr = [{"name": "leverage", "direction": "max",
                "thresholds": [{"period_end": "2025-09-30",
                                "applies_after": None, "value": 4.0,
                                "condition": None}]}]
        dis = [{"name": "leverage", "direction": "max", "threshold": 4.0,
                "waiver_or_amendment_note": None}]
        rows, _ = backtest_terms.score_terms(
            "TST", "2025-09-30", agr, dis, "http://u", [True], [True])
        self.assertTrue(rows[0]["repaired"])
        rows, _ = backtest_terms.score_terms(
            "TST", "2025-09-30", agr, dis, "http://u", [True])
        self.assertFalse(rows[0]["repaired"])


class ExtractOne(unittest.TestCase):
    def _disclosed_dir(self, tmp, disclosed=None):
        backtest_dir = Path(tmp) / "backtest"
        backtest_dir.mkdir()
        (backtest_dir / "disclosed_TST.json").write_text(
            json.dumps(disclosed if disclosed is not None else DISCLOSED),
            encoding="utf-8")
        return backtest_dir

    def test_ok_path_saves_terms(self):
        client = FakeClient([_response(json.dumps(PARSED))])
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = self._disclosed_dir(tmp)
            with (patch.object(backtest_terms, "select_agreement",
                               return_value=(BASE, [])) as sel,
                  patch.object(backtest_terms, "fetch_agreement",
                               return_value=(DOCUMENT, BASE["url"]))):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    record = backtest_terms.extract_one(
                        _case(), client, backtest_dir)
            sel.assert_called_once_with("TST", as_of="2025-11-14")
            self.assertEqual(record["status"], backtest_terms.STATUS_OK)
            self.assertEqual(record["agreement_url"], BASE["url"])
            self.assertEqual(len(record["covenants"]), 2)
            self.assertTrue(all(c["match"] for c in record["covenants"]))
            self.assertTrue(all(c["quote_verified"]
                                for c in record["covenants"]))
            self.assertEqual(
                record["covenants"][0]["agreement_threshold"], 4.0)
            self.assertEqual(record["unmatched_disclosed"], [])
            self.assertTrue((backtest_dir / "terms_TST.json").exists())
            self.assertTrue((backtest_dir / "terms_TST_raw.txt").exists())
            self.assertEqual(len(client.chat.completions.requests), 1)

    def test_too_long_skips_model(self):
        client = FakeClient([])
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp) / "backtest"
            with (patch.object(backtest_terms, "select_agreement",
                               return_value=(BASE, [])),
                  patch.object(backtest_terms, "fetch_agreement",
                               return_value=("x" * (backtest_terms.MAX_CHARS + 1),
                                             BASE["url"]))):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    record = backtest_terms.extract_one(
                        _case(), client, backtest_dir)
                self.assertIn("too long", buf.getvalue())
            self.assertEqual(record["status"], backtest_terms.STATUS_TOO_LONG)
            self.assertEqual(record["covenants"], [])
            self.assertEqual(client.chat.completions.requests, [])
            self.assertTrue((backtest_dir / "terms_TST.json").exists())

    def test_no_agreement(self):
        client = FakeClient([])
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp) / "backtest"
            with patch.object(backtest_terms, "select_agreement",
                               return_value=(None, [])):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    record = backtest_terms.extract_one(
                        _case(), client, backtest_dir)
            self.assertEqual(backtest_terms.STATUS_NO_AGREEMENT,
                             "base agreement not found")
            self.assertEqual(record["status"], "base agreement not found")
            self.assertIn("2015-01-01", record["searched_range"])
            self.assertIn(record["as_of"], record["searched_range"])
            self.assertIsNone(record["agreement_url"])
            self.assertEqual(client.chat.completions.requests, [])
            self.assertTrue((backtest_dir / "terms_TST.json").exists())

    def test_missing_disclosed_file(self):
        client = FakeClient([_response(json.dumps(PARSED))])
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp) / "backtest"
            backtest_dir.mkdir()
            with (patch.object(backtest_terms, "select_agreement",
                               return_value=(BASE, [])),
                  patch.object(backtest_terms, "fetch_agreement",
                               return_value=(DOCUMENT, BASE["url"]))):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    record = backtest_terms.extract_one(
                        _case(), client, backtest_dir)
                self.assertIn("no disclosed_TST.json", buf.getvalue())
        self.assertTrue(all(c["status"] == backtest_terms.ROW_NO_DISCLOSED
                            for c in record["covenants"]))

    def test_repairs_failed_covenant_quote(self):
        bad = json.loads(json.dumps(PARSED))
        bad["financial_covenants"][0]["quote"] = "not in the document"
        fixed = PARSED["financial_covenants"][0]["quote"]
        client = FakeClient([_response(json.dumps(bad)), _response(fixed)])
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = self._disclosed_dir(tmp)
            with (patch.object(backtest_terms, "select_agreement",
                               return_value=(BASE, [])),
                  patch.object(backtest_terms, "fetch_agreement",
                               return_value=(DOCUMENT, BASE["url"]))):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    record = backtest_terms.extract_one(
                        _case(), client, backtest_dir)
        self.assertEqual(len(client.chat.completions.requests), 2)
        covenants = record["covenants"]
        self.assertTrue(covenants[0]["quote_verified"])
        self.assertTrue(covenants[0]["repaired"])
        self.assertTrue(covenants[1]["quote_verified"])
        self.assertFalse(covenants[1]["repaired"])

    def test_record_carries_conditional_alternatives(self):
        parsed = json.loads(json.dumps(PARSED))
        parsed["financial_covenants"][0]["thresholds"] = TRS_SCHEDULE
        disclosed = json.loads(json.dumps(DISCLOSED))
        disclosed["covenants"][0]["waiver_or_amendment_note"] = TRS_HOLIDAY_NOTE
        client = FakeClient([_response(json.dumps(parsed))])
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = self._disclosed_dir(tmp, disclosed)
            with (patch.object(backtest_terms, "select_agreement",
                               return_value=(BASE, [])),
                  patch.object(backtest_terms, "fetch_agreement",
                               return_value=(DOCUMENT, BASE["url"]))):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    record = backtest_terms.extract_one(
                        _case(), client, backtest_dir)
        covenant = record["covenants"][0]
        self.assertEqual(covenant["agreement_threshold"], 4.0)
        self.assertTrue(covenant["match"])
        self.assertEqual(covenant["conditional_alternatives"],
                         [{"value": 4.5,
                           "condition": "during a Covenant Holiday Period"}])


class Main(unittest.TestCase):
    def test_skips_snbr(self):
        companies = [_case("SNBR", "2025-09-27"), _case("TRS")]
        with (patch.object(backtest_terms, "load_companies",
                            return_value=companies),
              patch.object(backtest_terms, "make_client") as client,
              patch.object(backtest_terms, "extract_one",
                            return_value={"ticker": "TRS", "status": "ok",
                                          "covenants": []}) as ext):
            buf = io.StringIO()
            with redirect_stdout(buf):
                records = backtest_terms.main(["backtest_terms.py"],
                                              backtest_dir=Path("/tmp"))
        client.assert_called_once_with()
        ext.assert_called_once()
        self.assertEqual(ext.call_args[0][0]["ticker"], "TRS")
        self.assertEqual(len(records), 1)

    def test_only_snbr_runs_nothing(self):
        companies = [_case("SNBR", "2025-09-27")]
        with (patch.object(backtest_terms, "load_companies",
                            return_value=companies),
              patch.object(backtest_terms, "make_client",
                            side_effect=AssertionError("no client needed"))):
            buf = io.StringIO()
            with redirect_stdout(buf):
                records = backtest_terms.main(["backtest_terms.py"],
                                              backtest_dir=Path("/tmp"))
        self.assertEqual(records, [])
        self.assertIn("no companies to run", buf.getvalue())

    def test_unknown_ticker_exits_2(self):
        with patch.object(backtest_terms, "load_companies",
                           return_value=[_case("TRS")]):
            with self.assertRaises(SystemExit) as ctx:
                backtest_terms.main(["backtest_terms.py", "NOPE"],
                                     backtest_dir=Path("/tmp"))
        self.assertEqual(ctx.exception.code, 2)

    def test_table_and_totals(self):
        records = [
            {"ticker": "A", "status": "ok",
             "covenants": [
                 {"name": "leverage", "direction": "max",
                  "agreement_threshold": 4.0, "disclosed_threshold": 4.0,
                  "match": True, "quote_verified": True,
                  "status": backtest_terms.ROW_MATCH,
                  "agreement_url": "http://a"},
                 {"name": "coverage", "direction": "min",
                  "agreement_threshold": 2.5, "disclosed_threshold": 2.0,
                  "match": False, "quote_verified": True,
                  "status": backtest_terms.ROW_AMENDED,
                  "agreement_url": "http://a"}]},
            {"ticker": "B", "status": "too long", "covenants": []},
            {"ticker": "C", "status": "ok",
             "covenants": [
                 {"name": "leverage", "direction": "max",
                  "agreement_threshold": 3.0, "disclosed_threshold": 3.5,
                  "match": False, "quote_verified": False,
                  "status": backtest_terms.ROW_MISMATCH,
                  "agreement_url": "http://c"}]},
        ]
        companies = [_case("A"), _case("B"), _case("C")]
        with (patch.object(backtest_terms, "load_companies",
                            return_value=companies),
              patch.object(backtest_terms, "make_client"),
              patch.object(backtest_terms, "extract_one",
                            side_effect=records)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                backtest_terms.main(["backtest_terms.py"],
                                     backtest_dir=Path("/tmp"))
        out = buf.getvalue()
        self.assertIn("totals: 3 covenants across 3 companies", out)
        self.assertIn("matched: 1/3", out)
        self.assertIn("amended after agreement: 1", out)
        self.assertIn("mismatched: 1", out)
        self.assertIn("quote verified: 2/3", out)
        self.assertIn("note: B status: too long", out)


class ResumeAndForce(unittest.TestCase):
    SAVED = {"ticker": "TRS", "period_end": "2025-09-30",
             "as_of": "2025-11-14", "agreement_url": "http://x",
             "agreement_filing_date": "2025-05-06", "status": "ok",
             "covenants": [], "unmatched_disclosed": []}

    def test_skips_existing_terms_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp)
            (backtest_dir / "terms_TRS.json").write_text(
                json.dumps(self.SAVED), encoding="utf-8")
            with (patch.object(backtest_terms, "load_companies",
                                return_value=[_case("TRS")]),
                  patch.object(backtest_terms, "make_client",
                                side_effect=AssertionError("no client")),
                  patch.object(backtest_terms, "extract_one",
                                side_effect=AssertionError("no run"))):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    records = backtest_terms.main(
                        ["backtest_terms.py"], backtest_dir=backtest_dir)
        self.assertEqual(records, [self.SAVED])
        self.assertIn("already done", buf.getvalue())

    def test_force_reruns_existing(self):
        fresh = {"ticker": "TRS", "status": "ok", "covenants": []}
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp)
            (backtest_dir / "terms_TRS.json").write_text(
                json.dumps(self.SAVED), encoding="utf-8")
            with (patch.object(backtest_terms, "load_companies",
                                return_value=[_case("TRS")]),
                  patch.object(backtest_terms, "make_client") as client,
                  patch.object(backtest_terms, "extract_one",
                                return_value=fresh) as ext):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    records = backtest_terms.main(
                        ["backtest_terms.py", "--force"],
                        backtest_dir=backtest_dir)
        client.assert_called_once_with()
        ext.assert_called_once()
        self.assertEqual(records, [fresh])

    def test_error_record_saved_and_continues(self):
        ok_b = {"ticker": "B", "status": "ok", "covenants": []}
        companies = [_case("A"), _case("B")]
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp)
            with (patch.object(backtest_terms, "load_companies",
                                return_value=companies),
                  patch.object(backtest_terms, "make_client"),
                  patch.object(backtest_terms, "extract_one",
                                side_effect=[RuntimeError("boom"), ok_b])):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    records = backtest_terms.main(
                        ["backtest_terms.py"], backtest_dir=backtest_dir)
            saved = json.loads(
                (backtest_dir / "terms_A.json").read_text(encoding="utf-8"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["status"], backtest_terms.STATUS_ERROR)
        self.assertIn("boom", records[0]["error"])
        self.assertEqual(saved["status"], backtest_terms.STATUS_ERROR)
        self.assertEqual(records[1], ok_b)
        self.assertIn("note: A status: error", buf.getvalue())

    def test_unknown_flag_exits_2(self):
        with patch.object(backtest_terms, "load_companies",
                           return_value=[_case("TRS")]):
            with self.assertRaises(SystemExit) as ctx:
                backtest_terms.main(["backtest_terms.py", "--bogus"],
                                     backtest_dir=Path("/tmp"))
        self.assertEqual(ctx.exception.code, 2)


class ExtractOneDiagnostics(unittest.TestCase):
    def _bad_parsed(self):
        bad = json.loads(json.dumps(PARSED))
        for cov in bad["financial_covenants"]:
            cov["quote"] = "zzz no such text here"
        bad["cap_groups"] = [
            {"id": "c1", "applies_to_clauses": [], "schedule": [],
             "quote": "yyy missing one"},
            {"id": "c2", "applies_to_clauses": [], "schedule": [],
             "quote": "xxx missing two"},
        ]
        return bad

    def test_failures_saved_in_raw_and_first_3_printed(self):
        # Two failing covenant quotes each get one repair attempt (which
        # still fails); cap-group quotes are not repaired.
        client = FakeClient([_response(json.dumps(self._bad_parsed())),
                             _response("still nowhere one"),
                             _response("still nowhere two")])
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp) / "backtest"
            backtest_dir.mkdir()
            (backtest_dir / "disclosed_TST.json").write_text(
                json.dumps(DISCLOSED), encoding="utf-8")
            with (patch.object(backtest_terms, "select_agreement",
                                return_value=(BASE, [])),
                  patch.object(backtest_terms, "fetch_agreement",
                                return_value=(DOCUMENT, BASE["url"]))):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    backtest_terms.extract_one(
                        _case(), client, backtest_dir)
            raw = (backtest_dir / "terms_TST_raw.txt").read_text(
                encoding="utf-8")
        self.assertIn(backtest_terms.DIAGNOSTICS_MARKER, raw)
        self.assertEqual(len(client.chat.completions.requests), 3)
        diags = json.loads(raw.split(backtest_terms.DIAGNOSTICS_MARKER)[1])
        self.assertEqual(len(diags), 4)
        for diag in diags:
            self.assertIn("matched_prefix_len", diag)
            self.assertIn("quote_next", diag)
            self.assertIn("source_context", diag)
        self.assertEqual(buf.getvalue().count("matched_prefix_len"), 3)


class ReverifyTerms(unittest.TestCase):
    def _saved(self, backtest_dir, raw_text=None):
        (backtest_dir / "terms_TST_raw.txt").write_text(
            raw_text if raw_text is not None else json.dumps(PARSED),
            encoding="utf-8")
        (backtest_dir / "terms_TST.json").write_text(
            json.dumps({"ticker": "TST", "agreement_url": BASE["url"]}),
            encoding="utf-8")

    def test_reverify_uses_saved_raw_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp)
            self._saved(backtest_dir)
            with patch.object(backtest_terms, "fetch_agreement",
                               return_value=(DOCUMENT, BASE["url"])) as fa:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    report = backtest_terms.reverify_terms(
                        _case(), backtest_dir)
        fa.assert_called_once()
        self.assertEqual(report["verified"], report["total"])
        self.assertGreater(report["total"], 0)
        self.assertEqual(report["diagnostics"], [])
        self.assertIn("verified/total", buf.getvalue())

    def test_reverify_ignores_appended_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp)
            raw = (json.dumps(PARSED) + backtest_terms.DIAGNOSTICS_MARKER
                   + json.dumps([{"matched_prefix_len": 1}]) + "\n")
            self._saved(backtest_dir, raw_text=raw)
            with patch.object(backtest_terms, "fetch_agreement",
                               return_value=(DOCUMENT, BASE["url"])):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    report = backtest_terms.reverify_terms(
                        _case(), backtest_dir)
        self.assertEqual(report["verified"], report["total"])

    def test_reverify_missing_raw_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                report = backtest_terms.reverify_terms(_case(), Path(tmp))
        self.assertIsNone(report)
        self.assertIn("no terms_TST_raw.txt", buf.getvalue())

    def test_main_reverify_mode_makes_no_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = Path(tmp)
            self._saved(backtest_dir)
            with (patch.object(backtest_terms, "load_companies",
                                return_value=[_case("TST")]),
                  patch.object(backtest_terms, "make_client",
                                side_effect=AssertionError("no client")),
                  patch.object(backtest_terms, "fetch_agreement",
                                return_value=(DOCUMENT, BASE["url"]))):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    reports = backtest_terms.main(
                        ["backtest_terms.py", "--reverify", "TST"],
                        backtest_dir=backtest_dir)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["ticker"], "TST")


class BuildRepairContent(unittest.TestCase):
    def test_includes_source_and_failed_quote(self):
        bad = json.loads(json.dumps(PARSED))
        bad["financial_covenants"][0]["quote"] = "not in the document"
        content = backtest_terms.build_repair_content(
            DOCUMENT, bad["financial_covenants"][0])
        self.assertIn(DOCUMENT, content)
        self.assertIn("not in the document", content)

    def test_includes_schedule_numbers(self):
        covenant = {"name": "Total Net Leverage Ratio",
                    "thresholds": TRS_SCHEDULE,
                    "quote": "not in the document"}
        content = backtest_terms.build_repair_content(DOCUMENT, covenant)
        self.assertIn("Total Net Leverage Ratio", content)
        self.assertIn("4.0", content)
        self.assertIn("4.5", content)
        self.assertIn("during a Covenant Holiday Period", content)

    def test_asks_for_verbatim_sentence_with_number(self):
        content = backtest_terms.build_repair_content(
            DOCUMENT, PARSED["financial_covenants"][0])
        self.assertIn("exact verbatim sentence from the document", content)
        self.assertIn("containing that number", content)
        self.assertIn("copy characters exactly", content.lower())

    def test_reuses_disclosed_repair_parsing(self):
        self.assertIs(backtest_terms.parse_repair_quote,
                      extract_disclosed.parse_repair_quote)
        self.assertIs(backtest_terms.REPAIR_INSTRUCTIONS,
                      extract_disclosed.REPAIR_INSTRUCTIONS)


class RepairQuotes(unittest.TestCase):
    def test_verified_quotes_need_no_repair(self):
        parsed = json.loads(json.dumps(PARSED))
        client = FakeClient([])
        backtest_terms.repair_quotes(parsed, DOCUMENT, client)
        self.assertEqual(client.chat.completions.requests, [])
        for entry in parsed["financial_covenants"]:
            self.assertTrue(entry["quote_verified"])
            self.assertFalse(entry["repaired"])

    def test_failed_quote_repaired_and_reverified(self):
        parsed = json.loads(json.dumps(PARSED))
        parsed["financial_covenants"][0]["quote"] = "not in the document"
        fixed = PARSED["financial_covenants"][0]["quote"]
        client = FakeClient([_response(fixed)])
        backtest_terms.repair_quotes(parsed, DOCUMENT, client)
        self.assertEqual(len(client.chat.completions.requests), 1)
        self.assertEqual(parsed["financial_covenants"][0]["quote"], fixed)
        self.assertTrue(parsed["financial_covenants"][0]["quote_verified"])
        self.assertTrue(parsed["financial_covenants"][0]["repaired"])
        self.assertTrue(parsed["financial_covenants"][1]["quote_verified"])
        self.assertFalse(parsed["financial_covenants"][1]["repaired"])

    def test_failed_repair_marks_unverified_with_one_attempt(self):
        parsed = json.loads(json.dumps(PARSED))
        parsed["financial_covenants"][0]["quote"] = "not in the document"
        client = FakeClient([_response("still not in the document")])
        backtest_terms.repair_quotes(parsed, DOCUMENT, client)
        self.assertEqual(len(client.chat.completions.requests), 1)
        self.assertFalse(parsed["financial_covenants"][0]["quote_verified"])
        self.assertTrue(parsed["financial_covenants"][0]["repaired"])

    def test_formatting_difference_needs_no_repair(self):
        # Source carries TriMas-style spacing ("1.00 ."); the clean
        # quote still verifies via normalize, with no repair request.
        doc = DOCUMENT.replace("4.00 to 1.00.", "4.00 to 1.00 .")
        parsed = json.loads(json.dumps(PARSED))
        client = FakeClient([])
        backtest_terms.repair_quotes(parsed, doc, client)
        self.assertEqual(client.chat.completions.requests, [])
        self.assertTrue(parsed["financial_covenants"][0]["quote_verified"])
        self.assertFalse(parsed["financial_covenants"][0]["repaired"])
        # Same when the spacing variant is on the quote side.
        parsed = json.loads(json.dumps(PARSED))
        parsed["financial_covenants"][1]["quote"] = (
            "Interest Expense Coverage Ratio shall not be less "
            "than 3.00 to 1.00 .")
        client = FakeClient([])
        backtest_terms.repair_quotes(parsed, DOCUMENT, client)
        self.assertEqual(client.chat.completions.requests, [])
        self.assertTrue(parsed["financial_covenants"][1]["quote_verified"])
        self.assertFalse(parsed["financial_covenants"][1]["repaired"])

    def test_repair_request_uses_model_params(self):
        parsed = json.loads(json.dumps(PARSED))
        parsed["financial_covenants"][0]["quote"] = "not in the document"
        client = FakeClient(
            [_response(PARSED["financial_covenants"][0]["quote"])])
        backtest_terms.repair_quotes(parsed, DOCUMENT, client)
        kwargs = client.chat.completions.requests[0]
        self.assertEqual(kwargs["model"], "meta-models/muse-spark-open-1026")
        self.assertEqual(kwargs["temperature"], 0)


if __name__ == "__main__":
    unittest.main()
