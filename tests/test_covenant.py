"""Focused tests for covenant argv, proforma scenarios, fallback, clauses, warnings."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import covenant


def _contract():
    return {
        "financial_covenants": [
            {"name": "Net Leverage Ratio", "direction": "max",
             "thresholds": [{"period_end": "2026-01-03", "applies_after": None,
                             "value": 4.5}]},
            {"name": "Interest Coverage Ratio", "direction": "min",
             "thresholds": [{"period_end": "2026-01-03", "applies_after": None,
                             "value": 2.1}]},
        ],
        "cap_groups": [
            {"applies_to_clauses": ["(a)(iv)", "(a)(viii)"],
             "schedule": [{"period_end": "2026-01-03", "applies_after": None,
                           "amount_usd": 25_000_000}]},
            {"applies_to_clauses": ["(a)(ix)"],
             "schedule": [{"period_end": "2026-01-03", "applies_after": None,
                           "amount_usd": 60_000_000}]},
        ],
        "definitions": [
            {"term": "Consolidated EBITDA", "components": [
                {"clause_ref": "base"}, {"clause_ref": "(a)(i)"},
                {"clause_ref": "(a)(ii)"}, {"clause_ref": "(a)(iii)"},
                {"clause_ref": "(a)(iv)"}, {"clause_ref": "(a)(v)"},
                {"clause_ref": "(a)(vi)"}, {"clause_ref": "(a)(viii)"},
                {"clause_ref": "(a)(ix)"}]},
            {"term": "Consolidated EBITDAR", "components": [
                {"clause_ref": "(a)"}, {"clause_ref": "(b)"}]},
            {"term": "Consolidated Rent Expense", "components": [
                {"clause_ref": "all"}]},
            {"term": "Net Leverage Ratio", "components": [
                {"clause_ref": "(a)(i)"}, {"clause_ref": "(a)(ii)"},
                {"clause_ref": "(a)(iii)"}, {"clause_ref": "(b)"}]},
        ],
    }


def _release(**overrides):
    adj = [
        {"line": "Depreciation and amortization", "value_thousands": 50_000},
        {"line": "Other non-recurring items", "value_thousands": 1_000},
        {"line": "Asset impairments", "value_thousands": 500},
    ]
    lev = [
        {"line": "Finance lease obligations", "value_thousands": 200},
        {"line": "Consolidated rent expense", "value_thousands": 100_000},
    ]
    rel = {"adjusted_ebitda_ttm": adj, "leverage_table_ttm": lev}
    rel.update(overrides)
    return rel


INSTANT_VALS = {
    "us-gaap:DebtCurrent": 500_000_000,
    "us-gaap:LettersOfCreditOutstandingAmount": 10_000_000,
    "us-gaap:OperatingLeaseLiability": 300_000_000,
    "us-gaap:CashAndCashEquivalentsAtCarryingValue": 10_000_000,
}

TTM_VALS = {
    "us-gaap:NetIncomeLoss": -50_000_000,
    "us-gaap:IncomeTaxExpenseBenefit": -5_000_000,
    "us-gaap:InterestExpenseNonoperating": 40_000_000,
    "us-gaap:DepreciationDepletionAndAmortization": 49_000_000,
    "us-gaap:ShareBasedCompensation": 5_000_000,
    "us-gaap:RestructuringCosts": 10_000_000,
    "us-gaap:AssetImpairmentCharges": 2_000_000,
    "us-gaap:OperatingLeaseCost": 99_000_000,
}


class ResolvePeriodEnd(unittest.TestCase):
    def test_default(self):
        self.assertEqual(covenant.resolve_period_end(["prog"]), "2025-09-27")

    def test_argv(self):
        self.assertEqual(
            covenant.resolve_period_end(["prog", "2026-01-03"]), "2026-01-03")


class MaterialWarning(unittest.TestCase):
    def test_small_absolute_diff_not_flagged(self):
        self.assertFalse(covenant.is_material_warning(1000, 51000))

    def test_large_but_small_pct_not_flagged(self):
        # diff 150k but only 0.15% of 100M
        self.assertFalse(covenant.is_material_warning(100_150_000, 100_000_000))

    def test_large_and_large_pct_flagged(self):
        self.assertTrue(covenant.is_material_warning(1_500_000, 1_000_000))

    def test_filter_keeps_only_material(self):
        warns = [("c", "e", 1000, 51000),
                 ("c", "e", 1_500_000, 1_000_000)]
        self.assertEqual(len(covenant.filter_data_quality_warnings(warns)), 1)


class TryReleaseLine(unittest.TestCase):
    def test_found(self):
        self.assertEqual(
            covenant.try_release_line(_release(), "leverage_table_ttm",
                                      "Finance lease obligations"), 200_000)

    def test_missing_line_returns_none(self):
        self.assertIsNone(
            covenant.try_release_line(_release(), "leverage_table_ttm", "Nope"))

    def test_none_release_returns_none(self):
        self.assertIsNone(
            covenant.try_release_line(None, "leverage_table_ttm",
                                      "Finance lease obligations"))

    def test_null_value_returns_none(self):
        rel = {"leverage_table_ttm": [{"line": "X", "value_thousands": None}]}
        self.assertIsNone(covenant.try_release_line(rel, "leverage_table_ttm", "X"))


class FindProforma(unittest.TestCase):
    def test_found(self):
        rel = {"adjusted_ebitda_ttm": [
            {"line": "Pro forma cost savings", "value_thousands": 40_000}]}
        self.assertEqual(covenant.find_proforma_in_release(rel),
                         ("Pro forma cost savings", 40_000_000))

    def test_not_found(self):
        self.assertIsNone(covenant.find_proforma_in_release(_release()))

    def test_none_release(self):
        self.assertIsNone(covenant.find_proforma_in_release(None))

    def test_no_space_with_cost(self):
        rel = {"leverage_table_ttm": [
            {"line": "Proforma annualized cost reductions",
             "value_thousands": 50_000}]}
        self.assertEqual(covenant.find_proforma_in_release(rel),
                         ("Proforma annualized cost reductions", 50_000_000))

    def test_case_insensitive(self):
        rel = {"adjusted_ebitda_ttm": [
            {"line": "PRO FORMA COST SAVINGS", "value_thousands": 1_000}]}
        self.assertEqual(covenant.find_proforma_in_release(rel),
                         ("PRO FORMA COST SAVINGS", 1_000_000))

    def test_proforma_without_cost_or_savings_ignored(self):
        rel = {"adjusted_ebitda_ttm": [
            {"line": "Pro forma adjustments", "value_thousands": 5_000}]}
        self.assertIsNone(covenant.find_proforma_in_release(rel))

    def test_cost_without_proforma_ignored(self):
        rel = {"adjusted_ebitda_ttm": [
            {"line": "Cost reductions", "value_thousands": 5_000}]}
        self.assertIsNone(covenant.find_proforma_in_release(rel))


class Reconciliation(unittest.TestCase):
    def _compute_with_company_ebitda(self, value_thousands):
        rel = _release()
        rel["leverage_table_ttm"] = list(rel["leverage_table_ttm"]) + [
            {"line": "Adjusted EBITDA", "value_thousands": value_thousands}]
        with (patch.object(covenant, "load_contract", return_value=_contract()),
              patch.object(covenant, "load_release", return_value=rel),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: INSTANT_VALS[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: TTM_VALS[c])):
            return covenant.compute("2026-01-03")

    def test_reconciled_within_tolerance(self):
        # Onya base EBITDA for fixtures is $53,500,000; 53,800 thousands
        # differs by $300,000 (< $1,000,000 / 1,000 thousands).
        result = self._compute_with_company_ebitda(53_800)
        rec = result.get("reconciliation")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["status"], "reconciled")
        self.assertIn("reconciled", rec["note"])
        comp = [c for c in result["components"]
                if c["name"] == "Covenant EBITDA reconciliation"][0]
        self.assertIn("reconciled", comp["note"])
        for key in ("net_leverage", "interest_coverage"):
            self.assertIn("company_reported", rec[key])
            self.assertIn("onya_strict", rec[key])

    def test_flagged_beyond_tolerance(self):
        # $60,000,000 company vs $53,500,000 Onya: diff $6,500,000.
        result = self._compute_with_company_ebitda(60_000)
        rec = result.get("reconciliation")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["status"], "flagged")
        self.assertEqual(rec["difference"], 6_500_000)
        comp = [c for c in result["components"]
                if c["name"] == "Covenant EBITDA reconciliation"][0]
        self.assertIn("reported covenant EBITDA exceeds capped calculation by $",
                      comp["note"])
        self.assertIn("request compliance certificate", comp["note"])
        self.assertTrue(comp["source"].startswith("release:"))
        for key in ("net_leverage", "interest_coverage"):
            self.assertIn("ratio", rec[key]["company_reported"])
            self.assertIn("ratio", rec[key]["onya_strict"])
        self.assertEqual(rec["net_leverage"]["onya_strict"]["ratio"],
                         result["net_leverage"]["ratio"])
        self.assertEqual(rec["interest_coverage"]["onya_strict"]["ratio"],
                         result["interest_coverage"]["ratio"])

    def test_absent_when_not_disclosed(self):
        with (patch.object(covenant, "load_contract", return_value=_contract()),
              patch.object(covenant, "load_release", return_value=_release()),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: INSTANT_VALS[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: TTM_VALS[c])):
            result = covenant.compute("2026-01-03")
        self.assertNotIn("reconciliation", result)


class RealNumbers20260103(unittest.TestCase):
    """Like-for-like reconciliation with real 2026-01-03 numbers (thousands).

    Company Adjusted EBITDA 78,255; Onya pre-pro-forma 68,802; pro forma
    50,000; rent 104,983; numerator 951,461.
    """

    def _compute_real(self):
        rel = {
            "adjusted_ebitda_ttm": [
                {"line": "Depreciation and amortization",
                 "value_thousands": 53169},
                {"line": "Other non-recurring items",
                 "value_thousands": 14699},
                {"line": "Asset impairments", "value_thousands": 0},
            ],
            "leverage_table_ttm": [
                {"line": "Finance lease obligations",
                 "value_thousands": 159},
                {"line": "Consolidated rent expense",
                 "value_thousands": 104983},
                {"line": "Adjusted EBITDA", "value_thousands": 78255},
                {"line": "Proforma annualized cost reductions",
                 "value_thousands": 50000},
            ],
        }
        instant_vals = {
            "us-gaap:DebtCurrent": 588_200_000,
            "us-gaap:LettersOfCreditOutstandingAmount": 8_800_000,
            "us-gaap:OperatingLeaseLiability": 354_302_000,
            "us-gaap:CashAndCashEquivalentsAtCarryingValue": 1_693_000,
        }
        ttm_vals = {
            "us-gaap:NetIncomeLoss": -131_958_000,
            "us-gaap:IncomeTaxExpenseBenefit": 35_984_000,
            "us-gaap:InterestExpenseNonoperating": 49_382_000,
            "us-gaap:DepreciationDepletionAndAmortization": 55_608_000,
            "us-gaap:ShareBasedCompensation": 6_282_000,
            "us-gaap:RestructuringCosts": 19_754_000,
            "us-gaap:AssetImpairmentCharges": 30_943_000,
            "us-gaap:OperatingLeaseCost": 104_797_000,
        }
        with (patch.object(covenant, "load_contract",
                           return_value=_contract()),
              patch.object(covenant, "load_release", return_value=rel),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: instant_vals[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: ttm_vals[c])):
            return covenant.compute("2026-01-03")

    def test_like_for_like_and_ratios(self):
        result = self._compute_real()
        self.assertEqual(result["numerator"], 951_461_000)
        rec = result.get("reconciliation")
        self.assertIsNotNone(rec)
        # diff = company - onya_pre_proforma = 78,255 - 68,802 = +9,453.
        self.assertEqual(rec["company_ebitda"], 78_255_000)
        self.assertEqual(rec["onya_ebitda"], 68_802_000)
        self.assertEqual(rec["difference"], 9_453_000)
        self.assertEqual(rec["difference_thousands"], 9_453)
        self.assertEqual(rec["status"], "flagged")
        self.assertIn("exceeds", rec["note"])
        self.assertNotIn("is below", rec["note"])
        # Company basis: 951,461 / (78,255 + 104,983 + 50,000) = 4.08 PASS.
        comp = rec["net_leverage"]["company_reported"]
        self.assertEqual(comp["ratio_2dp"], 4.08)
        self.assertTrue(comp["pass"])
        # Onya-strict: 951,461 / (68,802 + 104,983 + 50,000) = 4.25 PASS.
        strict = rec["net_leverage"]["onya_strict"]
        self.assertEqual(strict["ratio_2dp"], 4.25)
        self.assertTrue(strict["pass"])
        # Company basis interest coverage:
        # (78,255 + 50,000) / 49,382 = 2.60 PASS.
        ccov = rec["interest_coverage"]["company_reported"]
        self.assertEqual(ccov["ratio_2dp"], 2.60)
        self.assertTrue(ccov["pass"])
        # Without savings: 951,461 / (68,802 + 104,983) = 5.4749 -> 5.47 FAIL.
        # (Task text states 5.48; precise math gives 5.47.)
        sens = result.get("sensitivity_without_proforma")
        self.assertIsNotNone(sens)
        self.assertIn("without projected savings that require administrative agent approval",
                      sens["note"])
        slev = sens["net_leverage"]
        self.assertEqual(slev["ratio_2dp"], 5.47)
        self.assertFalse(slev["pass"])
        # Printed sensitivity line carries the label, ratio, and FAIL.
        buf = io.StringIO()
        with redirect_stdout(buf):
            covenant.print_result(result)
        out = buf.getvalue()
        self.assertIn("without projected savings that require administrative agent approval", out)
        self.assertIn("5.47", out)
        self.assertIn("FAIL", out)

    def test_negative_diff_message(self):
        rel = _release()
        rel["leverage_table_ttm"] = list(rel["leverage_table_ttm"]) + [
            {"line": "Adjusted EBITDA", "value_thousands": 40_000}]
        with (patch.object(covenant, "load_contract",
                           return_value=_contract()),
              patch.object(covenant, "load_release", return_value=rel),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: INSTANT_VALS[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: TTM_VALS[c])):
            result = covenant.compute("2026-01-03")
        rec = result.get("reconciliation")
        self.assertIsNotNone(rec)
        # Onya base is $53,500,000; company $40,000,000 is below.
        self.assertLess(rec["difference"], 0)
        self.assertEqual(rec["status"], "flagged")
        self.assertIn("is below", rec["note"])
        self.assertNotIn("exceeds", rec["note"])


class ClauseRefs(unittest.TestCase):
    def test_combined_and_bare_labels_not_allowed(self):
        allowed = covenant.allowed_clause_refs(_contract())
        self.assertIn("(a)(ix)", allowed)
        self.assertIn("base", allowed)
        self.assertNotIn("(a)(iv)+(a)(viii) cap", allowed)
        self.assertNotIn("EBITDAR (b)", allowed)

    def test_definition_form_valid(self):
        allowed = covenant.allowed_clause_refs(_contract())
        terms = covenant.definition_terms(_contract())
        self.assertTrue(covenant.is_valid_clause(
            "definition: Consolidated EBITDA", allowed, terms))
        self.assertFalse(covenant.is_valid_clause(
            "EBITDAR (b)", allowed, terms))


class ProformaScenarios(unittest.TestCase):
    def test_dual_scenarios_when_capped_but_undisclosed(self):
        with (patch.object(covenant, "load_contract", return_value=_contract()),
              patch.object(covenant, "load_release", return_value=_release()),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: INSTANT_VALS[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: TTM_VALS[c])):
            result = covenant.compute("2026-01-03")
        scenarios = result.get("proforma_scenarios")
        self.assertIsNotNone(scenarios)
        self.assertEqual(len(scenarios), 2)
        self.assertEqual(scenarios[0]["savings"], 0)
        self.assertEqual(scenarios[1]["savings"], 60_000_000)
        for sc in scenarios:
            self.assertIn("unverifiable: requires administrative agent approval", sc["note"])
            for key in ("net_leverage", "interest_coverage"):
                for field in ("ratio", "headroom", "pass"):
                    self.assertIn(field, sc[key])
        # base top-level matches savings=0 scenario
        self.assertEqual(result["net_leverage"]["ratio"],
                         scenarios[0]["net_leverage"]["ratio"])
        # clause labels all valid
        allowed = covenant.allowed_clause_refs(_contract())
        terms = covenant.definition_terms(_contract())
        for comp in result["components"]:
            self.assertTrue(
                covenant.is_valid_clause(comp["clause"], allowed, terms),
                comp["clause"])

    def test_reported_amount_used(self):
        rel = _release()
        rel["adjusted_ebitda_ttm"] = list(rel["adjusted_ebitda_ttm"]) + [
            {"line": "Pro forma cost savings", "value_thousands": 10_000}]
        with (patch.object(covenant, "load_contract", return_value=_contract()),
              patch.object(covenant, "load_release", return_value=rel),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: INSTANT_VALS[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: TTM_VALS[c])):
            result = covenant.compute("2026-01-03")
        self.assertNotIn("proforma_scenarios", result)
        proforma = [c for c in result["components"]
                    if c["name"] == "Pro forma cost savings"][0]
        self.assertEqual(proforma["value"], 10_000_000)
        self.assertTrue(proforma["source"].startswith("release:"))


class XbrlFallback(unittest.TestCase):
    def _compute_with(self, release):
        with (patch.object(covenant, "load_contract", return_value=_contract()),
              patch.object(covenant, "load_release", return_value=release),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: INSTANT_VALS[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: TTM_VALS[c])):
            return covenant.compute("2026-01-03")

    def test_da_falls_back_to_xbrl(self):
        rel = _release()
        rel["adjusted_ebitda_ttm"] = [
            e for e in rel["adjusted_ebitda_ttm"]
            if e["line"] != "Depreciation and amortization"]
        result = self._compute_with(rel)
        da = [c for c in result["components"]
              if c["name"] == "Depreciation and amortization"][0]
        self.assertEqual(da["value"], 49_000_000)
        self.assertIn("xbrl:", da["source"])
        self.assertIn("missing", da["note"].lower())

    def test_missing_without_fallback_raises(self):
        rel = _release()
        rel["adjusted_ebitda_ttm"] = [
            e for e in rel["adjusted_ebitda_ttm"]
            if e["line"] != "Other non-recurring items"]
        with self.assertRaises(ValueError):
            self._compute_with(rel)


class FindPriorFinanceLeases(unittest.TestCase):
    def _write(self, ext, date, value_thousands):
        payload = {
            "period_end": date,
            "leverage_table_ttm": [
                {"line": "Finance lease obligations",
                 "value_thousands": value_thousands},
            ],
        }
        (ext / f"snbr_release_{date}.json").write_text(json.dumps(payload))

    def test_returns_most_recent_earlier(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp) / "data" / "extracted"
            ext.mkdir(parents=True)
            self._write(ext, "2025-09-27", 180)
            self._write(ext, "2026-01-03", 159)
            self._write(ext, "2026-04-04", 999)
            with patch.object(covenant, "PROJECT_ROOT", Path(tmp)):
                self.assertEqual(
                    covenant.find_prior_finance_leases("2026-04-04"),
                    (159_000, "2026-01-03"))
                self.assertEqual(
                    covenant.find_prior_finance_leases("2026-01-03"),
                    (180_000, "2025-09-27"))
                self.assertIsNone(
                    covenant.find_prior_finance_leases("2025-09-27"))

    def test_skips_null_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp) / "data" / "extracted"
            ext.mkdir(parents=True)
            self._write(ext, "2025-09-27", 180)
            self._write(ext, "2026-01-03", None)
            with patch.object(covenant, "PROJECT_ROOT", Path(tmp)):
                self.assertEqual(
                    covenant.find_prior_finance_leases("2026-04-04"),
                    (180_000, "2025-09-27"))


class FinanceCarryForward(unittest.TestCase):
    def _compute(self, release, prior, instant_vals):
        with (patch.object(covenant, "load_contract",
                           return_value=_contract()),
              patch.object(covenant, "load_release",
                           return_value=release),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: instant_vals[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: TTM_VALS[c]),
              patch.object(covenant, "find_prior_finance_leases",
                           return_value=prior)):
            return covenant.compute("2026-01-03")

    def _component(self, result, name):
        return [c for c in result["components"] if c["name"] == name][0]

    def test_carry_forward_when_leverage_missing(self):
        rel = _release()
        rel["leverage_table_ttm"] = []
        result = self._compute(rel, (180_000, "2025-09-27"), INSTANT_VALS)
        fin = self._component(result, "Finance lease obligations")
        self.assertEqual(fin["value"], 180_000)
        self.assertEqual(fin["source"],
                         "estimate: carried forward from 2025-09-27")
        self.assertEqual(fin["note"], "immaterial; not disclosed this period")
        # Rent keeps the XBRL fallback; it is never carried forward.
        rent = self._component(result, "Consolidated rent expense")
        self.assertEqual(rent["value"], TTM_VALS["us-gaap:OperatingLeaseCost"])
        self.assertIn("xbrl:", rent["source"])

    def test_no_carry_forward_when_leverage_present(self):
        rel = _release()
        rel["leverage_table_ttm"] = [
            {"line": "Consolidated rent expense", "value_thousands": 100_000}]
        instant_vals = dict(
            INSTANT_VALS, **{"us-gaap:CapitalLeaseObligations": 123_000})
        result = self._compute(rel, (999_000, "2025-09-27"), instant_vals)
        fin = self._component(result, "Finance lease obligations")
        self.assertEqual(fin["value"], 123_000)
        self.assertIn("xbrl:", fin["source"])

    def test_xbrl_fallback_when_no_prior(self):
        rel = _release()
        rel["leverage_table_ttm"] = []
        instant_vals = dict(
            INSTANT_VALS, **{"us-gaap:CapitalLeaseObligations": 123_000})
        result = self._compute(rel, None, instant_vals)
        fin = self._component(result, "Finance lease obligations")
        self.assertEqual(fin["value"], 123_000)
        self.assertIn("xbrl:", fin["source"])


class RatioDriverFields(unittest.TestCase):
    def test_defined_numerator_and_denominator(self):
        lev = covenant.ratio_driver_fields(
            "net_leverage", 962_096_000, 43_230_000,
            146_296_000, 51_404_000)
        self.assertEqual(lev["numerator_label"],
                         "total debt including operating leases")
        self.assertEqual(lev["numerator_value"], 962_096_000)
        self.assertEqual(lev["denominator_label"], "Consolidated EBITDAR")
        self.assertEqual(lev["denominator_value"], 146_296_000)
        cov = covenant.ratio_driver_fields(
            "interest_coverage", 962_096_000, 43_230_000,
            146_296_000, 51_404_000)
        self.assertEqual(cov["numerator_label"], "Consolidated EBITDA")
        self.assertEqual(cov["numerator_value"], 43_230_000)
        self.assertEqual(cov["denominator_label"],
                         "Consolidated Interest Expense")
        self.assertEqual(cov["denominator_value"], 51_404_000)


class DebtComponentClauses(unittest.TestCase):
    def test_debt_side_components_use_net_leverage_definition(self):
        with (patch.object(covenant, "load_contract", return_value=_contract()),
              patch.object(covenant, "load_release", return_value=_release()),
              patch.object(covenant, "instant",
                           side_effect=lambda c, e: INSTANT_VALS[c]),
              patch.object(covenant, "ttm",
                           side_effect=lambda c, e: TTM_VALS[c])):
            result = covenant.compute("2026-01-03")
        debt_names = [
            "Borrowings under credit facility",
            "Outstanding letters of credit",
            "Finance lease obligations",
            "Operating lease liabilities",
            "Unrestricted US cash in excess of $40,000,000",
        ]
        by_name = {c["name"]: c for c in result["components"]}
        for name in debt_names:
            self.assertEqual(by_name[name]["clause"],
                             "definition: Net Leverage Ratio", name)


class WarningsForPeriod(unittest.TestCase):
    def test_only_quarters_inside_ttm_window_are_kept(self):
        warnings = [
            ("us-gaap:RestructuringCosts", "2024-12-28", 28_374_000, 3_006_000),
            ("us-gaap:RestructuringCosts", "2026-01-03", 48_128_000, 2_348_000),
            ("us-gaap:OperatingLeaseCost", "2021-10-02", 24_352_000, 25_632_000),
        ]
        with patch.object(covenant, "ttm_window_ends",
                          return_value=["2025-03-29", "2025-06-28",
                                        "2025-09-27", "2026-01-03"]):
            kept = covenant.warnings_for_period(warnings, "2026-01-03")
        self.assertEqual([w[1] for w in kept], ["2026-01-03"])


if __name__ == "__main__":
    unittest.main()
