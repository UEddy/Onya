"""Focused tests for src/project.py covenant projection."""

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

import project


def _contract():
    return {
        "financial_covenants": [
            {"name": "Net Leverage Ratio",
             "thresholds": [
                 {"period_end": "2026-01-03", "value": 4.5},
                 {"period_end": "2026-04-04", "value": 4.75},
                 {"period_end": "2026-07-04", "value": 4.8},
                 {"period_end": None, "applies_after": "2026-07-04",
                  "value": 4.0},
             ]},
        ],
        "cap_groups": [
            {"id": "wrong_id_on_purpose",
             "applies_to_clauses": ["(a)(ix)"],
             "schedule": [
                 {"period_end": "2026-04-04", "applies_after": None,
                  "amount_usd": 44_000_000},
             ]},
            {"id": "another_wrong_id",
             "applies_to_clauses": ["(a)(iv)", "(a)(viii)"],
             "schedule": [
                 {"period_end": "2026-04-04", "applies_after": None,
                  "amount_usd": 25_000_000},
             ]},
        ],
    }


def _write_release(directory, period, adjusted_thousands):
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "period_end": period,
        "adjusted_ebitda_ttm": [
            {"line": "Adjusted EBITDA", "value_thousands": adjusted_thousands},
        ],
        "leverage_table_ttm": [],
    }
    (directory / f"snbr_release_{period}.json").write_text(json.dumps(payload))


class ResolveBase(unittest.TestCase):
    def test_default(self):
        self.assertEqual(project.resolve_base(["prog"]), "2026-01-03")

    def test_argv(self):
        self.assertEqual(project.resolve_base(["prog", "2025-09-27"]),
                         "2025-09-27")


class FindNextTest(unittest.TestCase):
    def test_next_after_base(self):
        nxt, thr, _ = project.find_next_test(_contract(), "2026-01-03")
        self.assertEqual(nxt, "2026-04-04")
        self.assertEqual(thr, 4.75)

    def test_skips_applies_after_only(self):
        nxt, thr, _ = project.find_next_test(_contract(), "2026-04-04")
        self.assertEqual(nxt, "2026-07-04")
        self.assertEqual(thr, 4.8)

    def test_none_after_last_raises(self):
        with self.assertRaises(ValueError):
            project.find_next_test(_contract(), "2026-07-04")


class NextCaps(unittest.TestCase):
    def test_matched_by_clauses_not_id(self):
        caps = project.get_next_caps(_contract(), "2026-04-04")
        self.assertEqual(caps["ix_cap"], 44_000_000)
        self.assertEqual(caps["iv_viii_cap"], 25_000_000)

    def test_missing_group_raises(self):
        bad = {"financial_covenants": [], "cap_groups": []}
        with self.assertRaises(ValueError):
            project.get_next_caps(bad, "2026-04-04")


class ProjectedProforma(unittest.TestCase):
    def test_min_of_disclosed_and_cap(self):
        self.assertEqual(project.projected_proforma(50_000_000, 44_000_000),
                         44_000_000)
        self.assertEqual(project.projected_proforma(10_000_000, 44_000_000),
                         10_000_000)

    def test_none_cap_returns_disclosed(self):
        self.assertEqual(project.projected_proforma(50_000_000, None),
                         50_000_000)

    def test_zero_disclosed(self):
        self.assertEqual(project.projected_proforma(0, 44_000_000), 0)


class ProjectionMath(unittest.TestCase):
    def test_ratios_and_cushion(self):
        proj = project.project_ratios(
            numerator=951_461_000, rent=104_983_000,
            onya_pre=68_802_000, company_pre=78_255_000,
            proforma=44_000_000, threshold=4.75)
        self.assertEqual(proj["onya"]["ebitdar"], 217_785_000)
        self.assertEqual(proj["company"]["ebitdar"], 227_238_000)
        self.assertAlmostEqual(proj["onya"]["ratio"], 4.3688, places=3)
        self.assertAlmostEqual(proj["company"]["ratio"], 4.1871, places=3)
        self.assertTrue(proj["onya"]["pass"])
        self.assertTrue(proj["company"]["pass"])
        cush = project.cushions(proj, 951_461_000, 4.75)
        self.assertAlmostEqual(cush["required_ebitdar"],
                               951_461_000 / 4.75, places=2)
        self.assertAlmostEqual(cush["onya"], 17_477_421.05, places=0)
        self.assertAlmostEqual(cush["company"], 26_930_421.05, places=0)


class TrendAvgDecline(unittest.TestCase):
    def test_mean_of_negatives_over_last_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp) / "data" / "extracted"
            _write_release(ext, "2025-06-28", 90_000)
            _write_release(ext, "2025-09-27", 85_062)
            _write_release(ext, "2026-01-03", 78_255)
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                trend = project.load_trend("2026-01-03")
        self.assertEqual(len(trend["series"]), 3)
        self.assertEqual([c["change"] for c in trend["changes"]],
                         [-4_938_000, -6_807_000])
        self.assertEqual(trend["avg_decline"], -5_872_500.0)

    def test_ignores_periods_after_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp) / "data" / "extracted"
            _write_release(ext, "2025-09-27", 85_062)
            _write_release(ext, "2026-01-03", 78_255)
            _write_release(ext, "2026-04-04", 61_963)
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                trend = project.load_trend("2026-01-03")
        self.assertEqual(len(trend["series"]), 2)
        self.assertEqual(trend["avg_decline"], -6_807_000.0)

    def test_positive_change_excluded_from_mean(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp) / "data" / "extracted"
            _write_release(ext, "2025-06-28", 80_000)
            _write_release(ext, "2025-09-27", 85_000)  # +5M
            _write_release(ext, "2026-01-03", 83_000)  # -2M
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                trend = project.load_trend("2026-01-03")
        # last two changes: +5M, -2M -> mean of negatives = -2M
        self.assertEqual(trend["avg_decline"], -2_000_000.0)

    def test_no_negative_gives_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp) / "data" / "extracted"
            _write_release(ext, "2025-09-27", 80_000)
            _write_release(ext, "2026-01-03", 85_000)
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                trend = project.load_trend("2026-01-03")
        self.assertIsNone(trend["avg_decline"])

    def test_single_period_gives_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp) / "data" / "extracted"
            _write_release(ext, "2025-09-27", 85_062)
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                trend = project.load_trend("2025-09-27")
        self.assertEqual(trend["changes"], [])
        self.assertIsNone(trend["avg_decline"])


def _scenario(savings, ebitdar, ratio_2dp):
    return {
        "savings": savings,
        "ebitda": ebitdar - 103_066_000,
        "ebitdar": ebitdar,
        "net_leverage": {"ratio": ratio_2dp, "ratio_2dp": ratio_2dp,
                         "threshold": 4.75, "pass": ratio_2dp <= 4.75},
    }


def _write_result(directory, period, scenarios, file_proforma=0):
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "period_end": period,
        "numerator": 962_096_000,
        "ebitda": 43_230_000,
        "ebitdar": 146_296_000,
        "net_leverage": {"ratio": 6.58, "ratio_2dp": 6.58,
                         "threshold": 4.75, "pass": False},
        "components": [{"name": "Pro forma cost savings",
                        "value": file_proforma}],
        "proforma_scenarios": scenarios,
    }
    (directory / f"snbr_{period}.json").write_text(json.dumps(payload))


class LoadBacktest(unittest.TestCase):
    def test_matches_scenario_with_projected_savings(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = Path(tmp) / "data" / "results"
            _write_result(res, "2026-04-04",
                          [_scenario(0, 146_296_000, 6.58),
                           _scenario(44_000_000, 190_296_000, 5.06)])
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                back = project.load_backtest("2026-04-04", 44_000_000)
        self.assertEqual(back["like_for_like"]["savings"], 44_000_000)
        self.assertEqual(
            back["like_for_like"]["net_leverage"]["ratio_2dp"], 5.06)
        self.assertEqual(back["without_savings"]["savings"], 0)
        self.assertEqual(
            back["without_savings"]["net_leverage"]["ratio_2dp"], 6.58)
        # as-filed actual is kept alongside the matched scenarios
        self.assertEqual(back["net_leverage"]["ratio_2dp"], 6.58)

    def test_no_exact_match_gives_none_like_for_like(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = Path(tmp) / "data" / "results"
            _write_result(res, "2026-04-04",
                          [_scenario(0, 146_296_000, 6.58)])
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                back = project.load_backtest("2026-04-04", 44_000_000)
        self.assertIsNone(back["like_for_like"])
        self.assertEqual(
            back["without_savings"]["net_leverage"]["ratio_2dp"], 6.58)

    def test_missing_file_gives_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                self.assertIsNone(
                    project.load_backtest("2026-04-04", 44_000_000))


class QuartersAndRisk(unittest.TestCase):
    def test_boundaries(self):
        _, r = project.quarters_and_risk(1.99 * 100, -100)
        self.assertEqual(r, "HIGH")
        _, r = project.quarters_and_risk(2.0 * 100, -100)
        self.assertEqual(r, "MEDIUM")
        _, r = project.quarters_and_risk(3.99 * 100, -100)
        self.assertEqual(r, "MEDIUM")
        _, r = project.quarters_and_risk(4.0 * 100, -100)
        self.assertEqual(r, "LOW")

    def test_negative_cushion_is_high(self):
        q, r = project.quarters_and_risk(-5_000_000, -6_807_000)
        self.assertLess(q, 0)
        self.assertEqual(r, "HIGH")

    def test_no_decline_positive_cushion_is_low(self):
        q, r = project.quarters_and_risk(10_000_000, None)
        self.assertIsNone(q)
        self.assertEqual(r, "LOW")

    def test_no_decline_negative_cushion_is_high(self):
        q, r = project.quarters_and_risk(-1_000_000, None)
        self.assertIsNone(q)
        self.assertEqual(r, "HIGH")


class RealBase20260103(unittest.TestCase):
    def test_full_projection(self):
        with patch.object(project, "PROJECT_ROOT", FIXTURES):
            result = project.compute("2026-01-03")
        self.assertEqual(result["next_test"], "2026-04-04")
        self.assertEqual(result["next_threshold"], 4.75)
        self.assertEqual(result["ix_cap"], 44_000_000)
        self.assertEqual(result["iv_viii_cap"], 25_000_000)
        self.assertEqual(result["baseline"]["disclosed_proforma"], 50_000_000)
        self.assertEqual(result["projected_proforma"], 44_000_000)
        self.assertEqual(result["projections"]["onya"]["ratio_2dp"], 4.37)
        self.assertEqual(result["projections"]["company"]["ratio_2dp"], 4.19)
        self.assertTrue(result["projections"]["onya"]["pass"])
        self.assertAlmostEqual(result["cushion"]["onya"], 17_477_421.05,
                               places=0)
        self.assertEqual(result["trend"]["avg_decline"], -10_619_500.0)
        self.assertAlmostEqual(result["quarters_of_cushion"]["onya"], 1.65,
                               places=2)
        self.assertAlmostEqual(result["quarters_of_cushion"]["company"], 2.54,
                               places=2)
        self.assertEqual(result["risk"]["onya"], "HIGH")
        self.assertEqual(result["risk"]["company"], "MEDIUM")
        back = result["backtest"]
        self.assertIsNotNone(back)
        self.assertEqual(back["net_leverage"]["ratio_2dp"], 6.58)
        self.assertFalse(back["net_leverage"]["pass"])
        like = back["like_for_like"]
        self.assertEqual(like["savings"], 44_000_000)
        self.assertEqual(like["net_leverage"]["ratio_2dp"], 5.06)
        self.assertFalse(like["net_leverage"]["pass"])
        zero = back["without_savings"]
        self.assertEqual(zero["savings"], 0)
        self.assertEqual(zero["net_leverage"]["ratio_2dp"], 6.58)

    def test_print_includes_rule_and_backtest(self):
        with patch.object(project, "PROJECT_ROOT", FIXTURES):
            result = project.compute("2026-01-03")
        buf = io.StringIO()
        with redirect_stdout(buf):
            project.print_result(result)
        out = buf.getvalue()
        self.assertIn("Risk rule: HIGH if quarters_of_cushion < 2", out)
        self.assertIn("MEDIUM if < 4, else LOW", out)
        self.assertIn("backtest", out)
        self.assertIn("6.58", out)
        self.assertIn("5.06", out)
        self.assertIn("without savings", out)
        self.assertIn("4.37", out)

    def test_backtest_missing_reports_no_file(self):
        with patch.object(project, "PROJECT_ROOT", FIXTURES):
            result = project.compute("2026-04-04")
        self.assertIsNone(result["backtest"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            project.print_result(result)
        self.assertIn("no actual result file for 2026-07-04", buf.getvalue())


class SaveResult(unittest.TestCase):
    def test_writes_projection_file(self):
        with patch.object(project, "PROJECT_ROOT", FIXTURES):
            result = project.compute("2026-01-03")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(project, "PROJECT_ROOT", Path(tmp)):
                path = project.save_result(result)
                self.assertTrue(
                    path.name == "snbr_projection_2026-01-03.json")
                saved = json.loads(Path(path).read_text(encoding="utf-8"))
                self.assertEqual(saved["base"], "2026-01-03")
                self.assertEqual(saved["next_test"], "2026-04-04")


if __name__ == "__main__":
    unittest.main()
