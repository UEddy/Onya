"""Focused tests for covenant argv, proforma scenarios, fallback, clauses, warnings."""

import json
import sys
import tempfile
import unittest
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
            self.assertIn("unverifiable: requires agent approval", sc["note"])
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


if __name__ == "__main__":
    unittest.main()
