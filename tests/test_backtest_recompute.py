"""Recompute tests with fixture definitions and facts (no network, no model)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import backtest_recompute as br  # noqa: E402
import ttm  # noqa: E402


def definition(term, summary, labels):
    return {"term": term, "formula_summary": summary,
            "components": [{"label": label} for label in labels]}


CLOSED = "Net income plus interest, taxes and depreciation"
CLOSED_DEFS = [
    definition("Total Leverage Ratio", "Debt over EBITDA",
               ["Total Indebtedness", "Consolidated EBITDA"]),
    definition("Total Indebtedness", "Sum of borrowed money and finance leases",
               ["borrowed money", "Finance Lease Obligations"]),
    definition("Consolidated EBITDA", CLOSED,
               ["net income", "interest expense", "income tax",
                "depreciation and amortization"]),
]

FLOWS = {"net_income": 50, "interest": 10, "tax": 10,
         "depreciation_amortization": 30}
FLOW_BY_CONCEPT = {
    "us-gaap:NetIncomeLoss": 50, "us-gaap:InterestExpense": 10,
    "us-gaap:IncomeTaxExpenseBenefit": 10,
    "us-gaap:DepreciationDepletionAndAmortization": 30,
}
BALANCES = {"us-gaap:LongTermDebt": 400,
            "us-gaap:FinanceLeaseLiability": 20}


def flow(concept, _period_end, _cik):
    if concept not in FLOW_BY_CONCEPT:
        raise ValueError(concept)
    return FLOW_BY_CONCEPT[concept]


def instant(concept, _period_end, cik=None):
    if concept not in BALANCES:
        raise ValueError(concept)
    return BALANCES[concept]


def plan_for(defs, metric="Total Leverage Ratio"):
    parsed = {"definitions": defs}
    return br.build_plan(metric, br.definitions_by_term(parsed))[0]


class Plans(unittest.TestCase):
    def test_closed_definition_maps_with_nothing_missing(self):
        plan = plan_for(CLOSED_DEFS)
        self.assertEqual(plan["missing"], [])
        self.assertTrue(plan["debt"])
        self.assertTrue(plan["finance_lease"])
        self.assertEqual(plan["earnings"], set(FLOWS))

    def test_company_specific_add_back_is_listed_not_guessed(self):
        defs = [CLOSED_DEFS[0], CLOSED_DEFS[1], definition(
            "Consolidated EBITDA", CLOSED,
            ["net income", "run rate cost savings", "Heimbach charges"])]
        plan = plan_for(defs)
        self.assertIn("run rate cost savings: not available from XBRL",
                      plan["missing"])
        self.assertIn("Heimbach charges: not available from XBRL",
                      plan["missing"])

    def test_open_ended_summary_cannot_be_full(self):
        defs = [CLOSED_DEFS[0], CLOSED_DEFS[1], definition(
            "Consolidated EBITDA", "Net Income plus add-backs (a)(i)-(x)",
            ["net income"])]
        plan = plan_for(defs)
        self.assertTrue(any("did not itemize" in m for m in plan["missing"]))

    def test_guarantees_are_not_read_as_debt(self):
        defs = [definition("Total Leverage Ratio", "x",
                           ["Guarantees of borrowed money",
                            "Consolidated EBITDA"]),
                CLOSED_DEFS[2]]
        plan = plan_for(defs)
        self.assertFalse(plan["debt"])
        self.assertIn("Guarantees of borrowed money: not available from XBRL",
                      plan["missing"])

    def test_secured_subset_blocks_the_ratio(self):
        defs = [definition("Total Leverage Ratio", "x",
                           ["secured Total Net Debt", "Consolidated EBITDA"]),
                CLOSED_DEFS[2]]
        plan = plan_for(defs)
        self.assertTrue(plan["secured_subset"])
        recomputed, _c, _m = br.compute(plan, "2026-06-30", "1", flow, instant)
        self.assertIsNone(recomputed)

    def test_rent_multiple_is_read(self):
        defs = [definition("Total Leverage Ratio", "x",
                           ["Adjusted Debt", "Consolidated EBITDAR"]),
                definition("Adjusted Debt", "Debt plus rent times five",
                           ["funded debt", "Consolidated Rent Expense × 5.0"]),
                definition("Consolidated EBITDAR", CLOSED,
                           ["net income", "rent expense"])]
        plan = plan_for(defs)
        self.assertEqual(plan["rent_multiple"], 5.0)

    def test_undefined_ratio_is_partial_with_no_figure(self):
        plan = plan_for([CLOSED_DEFS[2]])
        self.assertEqual(
            plan["missing"],
            ["Total Leverage Ratio: ratio definition not extracted"])
        recomputed, _c, missing = br.compute(
            plan, "2026-06-30", "1", flow, instant)
        self.assertIsNone(recomputed)
        status, difference = br.judge(recomputed, 4.0, missing)
        self.assertEqual((status, difference), (br.STATUS_PARTIAL, None))


class Compute(unittest.TestCase):
    def test_full_mapping_computes_the_ratio(self):
        recomputed, components, missing = br.compute(
            plan_for(CLOSED_DEFS), "2026-06-30", "1", flow, instant)
        self.assertEqual(recomputed, 4.2)
        self.assertEqual(missing, [])
        self.assertEqual({c["component"] for c in components},
                         set(FLOWS) | {"debt", "finance_leases"})

    def test_missing_core_item_gives_no_figure(self):
        def no_tax(concept, period_end, cik):
            if concept == "us-gaap:IncomeTaxExpenseBenefit":
                raise ValueError(concept)
            return flow(concept, period_end, cik)

        recomputed, _c, missing = br.compute(
            plan_for(CLOSED_DEFS), "2026-06-30", "1", no_tax, instant)
        self.assertIsNone(recomputed)
        self.assertTrue(any(m.startswith("tax:") for m in missing))

    def test_negative_earnings_give_no_figure(self):
        def loss(concept, period_end, cik):
            if concept == "us-gaap:NetIncomeLoss":
                return -500
            return flow(concept, period_end, cik)

        recomputed, _c, _m = br.compute(
            plan_for(CLOSED_DEFS), "2026-06-30", "1", loss, instant)
        self.assertIsNone(recomputed)

    def test_debt_tag_with_leases_is_not_double_counted(self):
        balances = {"us-gaap:LongTermDebtAndCapitalLeaseObligations": 400,
                    "us-gaap:FinanceLeaseLiability": 20}

        def tagged(concept, _period_end, cik=None):
            if concept not in balances:
                raise ValueError(concept)
            return balances[concept]

        recomputed, _c, _m = br.compute(
            plan_for(CLOSED_DEFS), "2026-06-30", "1", flow, tagged)
        self.assertEqual(recomputed, 4.0)

    def test_net_interest_tag_uses_magnitude(self):
        def net(concept, _period_end, _cik):
            if concept == "us-gaap:InterestIncomeExpenseNet":
                return -25
            raise ValueError(concept)

        concepts, value = br._first_flow("interest", "2026-06-30", "1", net)
        self.assertEqual(concepts, ["us-gaap:InterestIncomeExpenseNet"])
        self.assertEqual(value, 25)

    def test_depreciation_falls_back_to_its_parts(self):
        def parts(concept, _period_end, _cik):
            if concept in br.DA_PARTS:
                return 7
            raise ValueError(concept)

        concepts, value = br._first_flow(
            "depreciation_amortization", "2026-06-30", "1", parts)
        self.assertEqual(concepts, list(br.DA_PARTS))
        self.assertEqual(value, 14)


class Judge(unittest.TestCase):
    def test_within_tolerance_is_a_match(self):
        self.assertEqual(br.judge(4.2, 4.1, []), (br.STATUS_MATCH, 0.1))

    def test_outside_tolerance_is_a_mismatch(self):
        self.assertEqual(br.judge(4.5, 4.1, []), (br.STATUS_MISMATCH, 0.4))

    def test_close_figure_with_gaps_stays_partial(self):
        self.assertEqual(br.judge(4.1, 4.1, ["Guarantees"]),
                         (br.STATUS_PARTIAL, 0.0))

    def test_no_disclosed_ratio_stays_partial(self):
        self.assertEqual(br.judge(4.1, None, []), (br.STATUS_PARTIAL, None))


class Company(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, value):
        text = value if isinstance(value, str) else json.dumps(value)
        (self.dir / name).write_text(text, encoding="utf-8")

    def test_no_saved_extraction_is_skipped(self):
        self.assertIsNone(br.recompute_company(
            {"ticker": "TST", "period_end": "2026-06-30"}, self.dir))

    def test_scanned_agreement_is_skipped(self):
        self.write("terms_TST.json", {"status": "agreement filed as scanned images"})
        self.write("terms_TST_raw.txt", "{}")
        self.assertIsNone(br.recompute_company(
            {"ticker": "TST", "period_end": "2026-06-30"}, self.dir))

    def test_saves_max_ratios_and_plain_labels(self):
        self.write("terms_TST.json", {"status": "ok", "agreement_url": "u"})
        cov = {"name": "Total Leverage Ratio \u2013 max",
               "metric_term": "Total Leverage Ratio", "direction": "max"}
        low = {"name": "Interest Coverage", "direction": "min"}
        self.write("terms_TST_raw.txt", json.dumps(
            {"financial_covenants": [cov, low], "definitions": CLOSED_DEFS}))
        self.write("disclosed_TST.json", {"covenants": [
            {"name": "total leverage ratio", "direction": "max", "actual": 4.15}]})
        with patch.object(br, "get_cik", return_value="1"), \
                patch.object(br, "resolve_period_end",
                             return_value="2026-06-30"), \
                patch.object(br, "compute", side_effect=br_compute):
            record = br.recompute_company(
                {"ticker": "TST", "period_end": "2026-06-30"}, self.dir)
        self.assertEqual(len(record["ratios"]), 1)
        ratio = record["ratios"][0]
        self.assertEqual(ratio["status"], br.STATUS_MATCH)
        self.assertEqual(ratio["difference"], 0.05)
        self.assertNotIn("\u2013", ratio["name"])
        saved = json.loads((self.dir / "recompute_TST.json").read_text())
        self.assertEqual(saved["ratios"][0]["recomputed"], 4.2)


_REAL_COMPUTE = br.compute


def br_compute(plan, end, cik):
    return _REAL_COMPUTE(plan, end, cik, flow, instant)


class AnnualFallback(unittest.TestCase):
    FACTS = {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-06-30", "val": 6, "form": "10-Q",
         "filed": "2025-08-01"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 27,
         "form": "DEF 14A", "filed": "2026-04-01"},
        {"start": "2026-01-01", "end": "2026-06-30", "val": 10, "form": "10-Q",
         "filed": "2026-08-01"},
    ]}}

    def test_year_plus_ytd_minus_prior_ytd(self):
        with patch.object(ttm, "_entry", return_value=self.FACTS):
            self.assertEqual(
                ttm.ttm_from_annual("us-gaap:X", "2026-06-30"), 31)

    def test_missing_prior_ytd_raises(self):
        facts = {"units": {"USD": [self.FACTS["units"]["USD"][i]
                                   for i in (1, 2)]}}
        with patch.object(ttm, "_entry", return_value=facts):
            with self.assertRaises(ValueError):
                ttm.ttm_from_annual("us-gaap:X", "2026-06-30")

    def test_stale_annual_raises(self):
        facts = {"units": {"USD": [self.FACTS["units"]["USD"][1]]}}
        with patch.object(ttm, "_entry", return_value=facts):
            with self.assertRaises(ValueError):
                ttm.ttm_from_annual("us-gaap:X", "2027-06-30")


if __name__ == "__main__":
    unittest.main()
