"""Focused tests for src/cure.py with real 2026-04-04 numbers."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import cure

# Real filed figures from tests/fixtures (10-K/10-Q-only XBRL).
NUMERATOR = 962_096_000
EBITDA = 43_230_000
EBITDAR = 146_296_000
INTEREST = 51_404_000
LEV_THRESHOLD = 4.75
COV_THRESHOLD = 2.1
SC_EBITDA = 87_230_000
SC_EBITDAR = 190_296_000

# Real filed figures from tests/fixtures (passing).
P_NUMERATOR = 951_461_000
P_EBITDA = 118_802_000
P_EBITDAR = 223_785_000
P_INTEREST = 49_382_000
P_LEV_THRESHOLD = 4.5
P_COV_THRESHOLD = 2.1


def _result_2026_04_04():
    return {
        "period_end": "2026-04-04",
        "numerator": NUMERATOR,
        "ebitda": EBITDA,
        "ebitdar": EBITDAR,
        "components": [
            {"name": "Interest expense", "value": INTEREST,
             "source": "xbrl:us-gaap:InterestExpenseNonoperating"},
        ],
        "net_leverage": {"ratio": 6.58, "threshold": LEV_THRESHOLD,
                         "pass": False},
        "interest_coverage": {"ratio": 0.84, "threshold": COV_THRESHOLD,
                              "pass": False},
        "proforma_scenarios": [
            {"savings": 0, "ebitda": EBITDA, "ebitdar": EBITDAR,
             "net_leverage": {"ratio": 6.58, "threshold": LEV_THRESHOLD,
                              "pass": False},
             "interest_coverage": {"ratio": 0.84,
                                   "threshold": COV_THRESHOLD, "pass": False}},
            {"savings": 44_000_000, "ebitda": SC_EBITDA,
             "ebitdar": SC_EBITDAR,
             "net_leverage": {"ratio": 5.06, "threshold": LEV_THRESHOLD,
                              "pass": False},
             "interest_coverage": {"ratio": 1.7,
                                   "threshold": COV_THRESHOLD, "pass": False}},
        ],
    }


def _result_2026_01_03():
    return {
        "period_end": "2026-01-03",
        "numerator": P_NUMERATOR,
        "ebitda": P_EBITDA,
        "ebitdar": P_EBITDAR,
        "components": [
            {"name": "Interest expense", "value": P_INTEREST,
             "source": "xbrl:us-gaap:InterestExpenseNonoperating"},
        ],
        "net_leverage": {"ratio": 4.25, "threshold": P_LEV_THRESHOLD,
                         "pass": True},
        "interest_coverage": {"ratio": 2.41, "threshold": P_COV_THRESHOLD,
                              "pass": True},
    }


def _contract_no_cure():
    return {"financial_covenants": [
        {"name": "Net Leverage Ratio",
         "quote": "shall not suffer or permit the ratio to exceed"}],
        "definitions": [],
        "uncertainties": ["forecast dollar amounts cannot be verified"]}


def _compute(result, contract=None):
    with (patch.object(cure, "load_result", return_value=result),
          patch.object(cure, "load_contract",
                       return_value=_contract_no_cure()
                       if contract is None else contract)):
        return cure.compute(result["period_end"])


class ResolvePeriodEnd(unittest.TestCase):
    def test_default(self):
        self.assertEqual(cure.resolve_period_end(["prog"]), "2026-04-04")

    def test_argv(self):
        self.assertEqual(
            cure.resolve_period_end(["prog", "2026-01-03"]), "2026-01-03")


class RealNumbers20260404(unittest.TestCase):
    def test_base_net_leverage_shortfall(self):
        c = _compute(_result_2026_04_04())
        lev = c["base"]["net_leverage"]
        self.assertEqual(lev["status"], "fail")
        figs = lev["figures"]
        # 962,096,000 - 4.75 x 146,296,000 = 267,190,000.
        self.assertEqual(figs["debt_reduction_needed"]["value"], 267_190_000)
        # 962,096,000 / 4.75 - 146,296,000 = 56,250,526.32.
        self.assertAlmostEqual(figs["ebitda_increase_needed"]["value"],
                               56_250_526.32, places=2)
        # Reversibility: removing the shortfall lands exactly on threshold.
        self.assertAlmostEqual(
            (NUMERATOR - figs["debt_reduction_needed"]["value"]) / EBITDAR,
            LEV_THRESHOLD)
        self.assertAlmostEqual(
            NUMERATOR / (EBITDAR + figs["ebitda_increase_needed"]["value"]),
            LEV_THRESHOLD)

    def test_base_interest_coverage_shortfall(self):
        c = _compute(_result_2026_04_04())
        cov = c["base"]["interest_coverage"]
        self.assertEqual(cov["status"], "fail")
        figs = cov["figures"]
        # 2.1 x 51,404,000 - 43,230,000 = 64,718,400.
        self.assertEqual(figs["ebitda_increase_needed"]["value"], 64_718_400)
        # 51,404,000 - 43,230,000 / 2.1 = 30,818,285.71.
        self.assertAlmostEqual(figs["interest_reduction_needed"]["value"],
                               30_818_285.71, places=2)
        self.assertAlmostEqual(
            (EBITDA + figs["ebitda_increase_needed"]["value"]) / INTEREST,
            COV_THRESHOLD)

    def test_proforma_scenario_44m(self):
        c = _compute(_result_2026_04_04())
        scenarios = c["proforma_scenarios"]
        self.assertEqual(len(scenarios), 2)
        sc = [s for s in scenarios if s["savings"] == 44_000_000][0]
        lev_figs = sc["net_leverage"]["figures"]
        # 962,096,000 - 4.75 x 190,296,000 = 58,190,000.
        self.assertEqual(lev_figs["debt_reduction_needed"]["value"],
                         58_190_000)
        # 962,096,000 / 4.75 - 190,296,000 = 12,250,526.32.
        self.assertAlmostEqual(lev_figs["ebitda_increase_needed"]["value"],
                               12_250_526.32, places=2)
        cov_figs = sc["interest_coverage"]["figures"]
        # 2.1 x 51,404,000 - 87,230,000 = 20,718,400.
        self.assertEqual(cov_figs["ebitda_increase_needed"]["value"],
                         20_718_400)
        # 51,404,000 - 87,230,000 / 2.1 = 9,865,904.76.
        self.assertAlmostEqual(cov_figs["interest_reduction_needed"]["value"],
                               9_865_904.76, places=2)

    def test_every_figure_states_formula_and_sourced_inputs(self):
        c = _compute(_result_2026_04_04())
        self.assertIn("numerator - threshold x EBITDAR",
                      c["base"]["net_leverage"]["figures"]
                      ["debt_reduction_needed"]["formula"])
        self.assertIn("threshold x interest - EBITDA",
                      c["base"]["interest_coverage"]["figures"]
                      ["ebitda_increase_needed"]["formula"])
        lev_inputs = c["base"]["net_leverage"]["inputs"]
        self.assertEqual(lev_inputs["numerator"]["source"],
                         "result:numerator")
        self.assertEqual(lev_inputs["ebitdar"]["source"], "result:ebitdar")
        self.assertEqual(lev_inputs["threshold"]["source"],
                         "result:net_leverage.threshold")
        cov_inputs = c["base"]["interest_coverage"]["inputs"]
        self.assertIn("xbrl:us-gaap:InterestExpenseNonoperating",
                      cov_inputs["interest"]["source"])
        sc = c["proforma_scenarios"][1]
        self.assertEqual(
            sc["net_leverage"]["inputs"]["ebitdar"]["source"],
            "result:proforma_scenarios[1].ebitdar")

    def test_plain_english_summaries(self):
        c = _compute(_result_2026_04_04())
        self.assertEqual(
            c["base"]["net_leverage"]["summary"],
            "To pass Net Leverage at 4.75x, debt must fall by "
            "$267,190,000 or EBITDA must rise by $56,250,526.")
        self.assertEqual(
            c["base"]["interest_coverage"]["summary"],
            "To pass Interest Coverage at 2.1x, EBITDA must rise by "
            "$64,718,400 or interest must fall by $30,818,286.")

    def test_end_to_end_with_filed_result_and_contract(self):
        with patch.object(cure, "PROJECT_ROOT", FIXTURES):
            c = cure.compute("2026-04-04")
        self.assertEqual(c["period_end"], "2026-04-04")
        self.assertEqual(c["interest"]["value"], INTEREST)
        figs = c["base"]["net_leverage"]["figures"]
        self.assertEqual(figs["debt_reduction_needed"]["value"], 267_190_000)
        self.assertFalse(c["equity_cure"]["found"])


class PassingCushions(unittest.TestCase):
    def test_real_2026_01_03_cushions(self):
        c = _compute(_result_2026_01_03())
        lev_figs = c["base"]["net_leverage"]["figures"]
        # 4.5 x 223,785,000 - 951,461,000 = 55,571,500.
        self.assertEqual(lev_figs["debt_capacity"]["value"], 55_571_500)
        # 223,785,000 - 951,461,000 / 4.5 = 12,349,222.22.
        self.assertAlmostEqual(lev_figs["ebitda_cushion"]["value"],
                               12_349_222.22, places=2)
        cov_figs = c["base"]["interest_coverage"]["figures"]
        # 118,802,000 - 2.1 x 49,382,000 = 15,099,800.
        self.assertEqual(cov_figs["ebitda_cushion"]["value"], 15_099_800)
        # 118,802,000 / 2.1 - 49,382,000 = 7,190,380.95.
        self.assertAlmostEqual(cov_figs["interest_cushion"]["value"],
                               7_190_380.95, places=2)
        self.assertIn("passes at 4.5x",
                      c["base"]["net_leverage"]["summary"])
        self.assertIn("passes at 2.1x",
                      c["base"]["interest_coverage"]["summary"])

    def test_no_proforma_key_when_absent(self):
        c = _compute(_result_2026_01_03())
        self.assertNotIn("proforma_scenarios", c)


class EquityCure(unittest.TestCase):
    def test_not_found_in_real_contract(self):
        contract = json.loads(
            (PROJECT_ROOT / "data" / "extracted"
             / "snbr_covenants.reviewed.json").read_text(encoding="utf-8"))
        self.assertEqual(cure.find_equity_cure(contract), [])

    def test_generic_cure_wording_is_not_an_equity_cure(self):
        contract = {"notes": ["may cure any ambiguity, defect or "
                              "inconsistency in the loan documents"]}
        self.assertEqual(cure.find_equity_cure(contract), [])

    def test_provision_reported_when_present(self):
        contract = {"covenants": [
            {"name": "Equity Cure",
             "text": "the Borrower may cure a covenant breach with "
                     "a cash equity contribution"}]}
        hits = cure.find_equity_cure(contract)
        # Both the "Equity Cure" name and the provision text hit.
        self.assertEqual(len(hits), 2)
        self.assertTrue(all("equit" in h["text"].lower()
                            and "cure" in h["text"].lower() for h in hits))
        c = _compute(_result_2026_04_04(), contract=contract)
        self.assertTrue(c["equity_cure"]["found"])
        self.assertEqual(len(c["equity_cure"]["provisions"]), 2)

    def test_print_not_found_line(self):
        c = _compute(_result_2026_04_04())
        buf = io.StringIO()
        with redirect_stdout(buf):
            cure.print_result(c)
        out = buf.getvalue()
        self.assertIn("equity cure: not found in extracted terms", out)
        self.assertIn("To pass Net Leverage at 4.75x, debt must fall by "
                      "$267,190,000", out)
        self.assertIn("pro forma savings=$44,000,000", out)

    def test_print_provision_when_present(self):
        contract = {"equity_cure": "equity cure: cash equity cures breach"}
        c = _compute(_result_2026_04_04(), contract=contract)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cure.print_result(c)
        out = buf.getvalue()
        self.assertIn("equity cure (equity_cure)", out)
        self.assertNotIn("not found in extracted terms", out)


class EquityCureField(unittest.TestCase):
    def test_present_true_reported_from_field(self):
        contract = {"equity_cure": {
            "present": True, "section": "5.7(f)",
            "max_uses": "twice in any four-quarter period",
            "limits": "cure amount capped at $10,000,000",
            "how_applied": "deemed increase to Consolidated EBITDA",
            "quote": "the Borrower may effect an Equity Cure"}}
        c = _compute(_result_2026_04_04(), contract=contract)
        eq = c["equity_cure"]
        self.assertTrue(eq["found"])
        self.assertTrue(eq["present"])
        self.assertEqual(eq["section"], "5.7(f)")
        self.assertEqual(eq["limits"], "cure amount capped at $10,000,000")
        buf = io.StringIO()
        with redirect_stdout(buf):
            cure.print_result(c)
        out = buf.getvalue()
        self.assertIn("5.7(f)", out)
        self.assertNotIn("not found in extracted terms", out)

    def test_present_false_ignores_stray_wording(self):
        contract = {
            "equity_cure": {"present": False, "section": None,
                            "max_uses": None, "limits": None,
                            "how_applied": None, "quote": None},
            "notes": ["an equity cure cash contribution cures breach"],
        }
        c = _compute(_result_2026_04_04(), contract=contract)
        self.assertFalse(c["equity_cure"]["found"])
        self.assertFalse(c["equity_cure"]["present"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            cure.print_result(c)
        self.assertIn("equity cure: not found in extracted terms",
                      buf.getvalue())


class SaveAndErrors(unittest.TestCase):
    def test_save_adds_cure_key_preserving_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            res_dir = Path(tmp) / "data" / "results"
            res_dir.mkdir(parents=True)
            payload = _result_2026_04_04()
            (res_dir / "snbr_2026-04-04.json").write_text(
                json.dumps(payload))
            with patch.object(cure, "PROJECT_ROOT", Path(tmp)):
                path = cure.save_result("2026-04-04",
                                        {"period_end": "2026-04-04"})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["cure"],
                             {"period_end": "2026-04-04"})
            self.assertEqual(saved["numerator"], NUMERATOR)
            self.assertEqual(len(saved["proforma_scenarios"]), 2)

    def test_missing_result_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cure, "PROJECT_ROOT", Path(tmp)):
                with self.assertRaises(ValueError):
                    cure.load_result("2026-04-04")

    def test_missing_interest_component_raises(self):
        result = _result_2026_04_04()
        result["components"] = []
        with (patch.object(cure, "load_result", return_value=result),
              patch.object(cure, "load_contract",
                           return_value=_contract_no_cure())):
            with self.assertRaises(ValueError):
                cure.compute("2026-04-04")


if __name__ == "__main__":
    unittest.main()
