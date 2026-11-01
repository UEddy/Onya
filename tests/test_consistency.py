"""One source of truth: watchlist, case payload, cure, projection, memo.

Every figure for the Apr 4, 2026 Sleep Number test must agree across the
API surface, the shared what-if fixture, and the saved sample memo.
"""

import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402

FIXTURE = PROJECT_ROOT / "web" / "lib" / "what-if.fixture.json"
SAMPLE = PROJECT_ROOT / "data" / "samples" / "snbr_memo.json"


def _numbers(obj):
    out = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(_numbers(value))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            out.extend(_numbers(value))
    return out


class Consistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client = TestClient(api.app)
        cls.companies = client.get("/companies").json()["companies"]
        cls.period = client.get("/company/SNBR/period/2026-04-04").json()
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.sample = json.loads(SAMPLE.read_text(encoding="utf-8"))

    def snbr_row(self):
        return next(c for c in self.companies if c["ticker"] == "SNBR")

    def test_watchlist_matches_case_payload(self):
        row = self.snbr_row()
        period = self.period
        scenarios = {
            s["savings"]: s for s in period["scenarios"]
        }
        self.assertEqual(row["period_end"], "2026-04-04")
        self.assertEqual(row["as_of"], "2026-04-04")
        self.assertEqual(row["ratio_without_savings"],
                         scenarios[0]["net_leverage"]["ratio_2dp"])
        self.assertEqual(row["ratio_with_savings"],
                         scenarios[44000000]["net_leverage"]["ratio_2dp"])
        self.assertEqual(row["ratio"], row["ratio_without_savings"])
        self.assertEqual(row["threshold"],
                         period["net_leverage"]["threshold"])
        self.assertEqual(row["headroom"],
                         scenarios[0]["net_leverage"]["headroom_2dp"])
        self.assertEqual(row["status"], "fail")

    def test_case_payload_figures(self):
        period = self.period
        self.assertEqual(period["numerator"], 962096000)
        self.assertEqual(period["ebitdar"], 146296000)
        self.assertEqual(period["ebitda"], 43230000)
        self.assertEqual(
            period["interest_coverage"]["denominator_value"], 51404000)
        disallowed = next(
            c for c in period["components"]
            if c["name"].startswith("Disallowed"))
        self.assertEqual(abs(disallowed["value"]), 18732000)
        self.assertEqual(period["net_leverage"]["ratio_2dp"], 6.58)
        self.assertEqual(period["interest_coverage"]["ratio_2dp"], 0.84)

    def test_fixture_matches_case_payload(self):
        base = self.fixture["base"]
        period = self.period
        self.assertEqual(base["total_debt"], period["numerator"])
        self.assertEqual(base["ebitdar"], period["ebitdar"])
        self.assertEqual(base["ebitda"], period["ebitda"])
        self.assertEqual(base["interest_expense"],
                         period["interest_coverage"]["denominator_value"])
        self.assertEqual(base["net_leverage_limit"],
                         period["net_leverage"]["threshold"])
        self.assertEqual(base["interest_coverage_limit"],
                         period["interest_coverage"]["threshold"])
        self.assertEqual(base["savings_cap"], 44000000)

    def test_cure_figures(self):
        cure = self.period["cure"]
        base = cure["base"]
        self.assertEqual(
            base["net_leverage"]["figures"]["debt_reduction_needed"]["value"],
            267190000.0)
        self.assertAlmostEqual(
            base["net_leverage"]["figures"]["ebitda_increase_needed"]["value"],
            56250526.32, places=2)
        self.assertEqual(
            base["interest_coverage"]["figures"]["ebitda_increase_needed"]["value"],
            64718400.0)
        with_savings = next(
            s for s in cure["proforma_scenarios"] if s["savings"] == 44000000)
        self.assertEqual(
            with_savings["net_leverage"]["figures"]["debt_reduction_needed"]["value"],
            58190000.0)
        self.assertAlmostEqual(
            with_savings["net_leverage"]["figures"]["ebitda_increase_needed"]["value"],
            12250526.32, places=2)
        self.assertEqual(
            with_savings["interest_coverage"]["figures"]["ebitda_increase_needed"]["value"],
            20718400.0)
        self.assertFalse(cure["equity_cure"]["present"])

    def test_projection_jul_2026(self):
        projection = self.period["projection"]
        self.assertEqual(projection["next_test"], "2026-07-04")
        self.assertEqual(projection["next_threshold"], 4.8)
        onya = projection["projections"]["onya"]
        self.assertEqual(onya["ratio_2dp"], 6.58)
        self.assertEqual(onya["threshold"], 4.8)
        self.assertAlmostEqual(
            projection["cushion"]["onya_shortfall_to_pass"],
            54140666.67, places=2)

    def test_sample_memo_every_number_maps(self):
        period = self.period
        allowed = _numbers(period) + _numbers(self.snbr_row())
        allowed += [44000000.0]
        memo = self.sample["memo"]
        # Exact dollars and $X million forms.
        for raw in re.findall(r"\$([\d,]+(?:\.\d+)?)( million|M)?", memo):
            text, million = raw
            value = float(text.replace(",", ""))
            if million:
                value *= 1_000_000
                tolerance = 50000
            else:
                tolerance = 1
            self.assertTrue(
                any(abs(value - a) <= tolerance for a in allowed),
                f"memo amount ${text}{million} maps to no API field")
        # Ratios in Nx form (dates have no x suffix).
        for raw in re.findall(r"(\d+\.\d+)x", memo):
            value = float(raw)
            self.assertTrue(
                any(abs(value - abs(a)) <= 0.011 for a in allowed),
                f"memo ratio {raw}x maps to no API field")
        # Saved figure_fields agree with the period payload.
        by_field = {
            "total_debt": [period["numerator"]],
            "ebitdar": [period["ebitdar"]],
            "ebitda": [period["ebitda"]],
            "interest_expense":
                [period["interest_coverage"]["denominator_value"]],
            "cure.debt_reduction": [267190000.0, 58190000.0],
            "cure.ebitda_increase": [56250526.32, 12250526.32],
            "cure.interest_ebitda_increase": [64718400.0, 20718400.0],
        }
        for entry in self.sample["figure_fields"]:
            self.assertIn(entry["raw"], memo)
            if entry["field"] in by_field:
                self.assertTrue(
                    any(abs(entry["value"] - v) <= 300000
                        for v in by_field[entry["field"]]),
                    f"{entry['field']}={entry['value']} disagrees with cure")


if __name__ == "__main__":
    unittest.main()
