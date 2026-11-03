"""The Rewind view matches the case page and stays within each as-of date."""

import json
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("SEC_USER_AGENT", "onya-tests test@example.invalid")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import xbrl  # noqa: E402

CLIENT = TestClient(api.app)


def rewind():
    r = CLIENT.get("/company/SNBR/rewind")
    assert r.status_code == 200
    return r.json()


def period(step):
    r = CLIENT.get(f"/company/SNBR/period/{step['period_end']}")
    assert r.status_code == 200
    return r.json()


class Rewind(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(
            [(s["period_end"], s["as_of"], s["word"], s["verdict"])
             for s in rewind()["steps"]],
            [("2025-09-27", "2025-11-11", "Pass",
              "4.97x against 5.25x: pass."),
             ("2026-01-03", "2026-03-12", "Pass with savings",
              "4.25x against 4.50x: pass only with $50M of projected "
              "savings; 5.47x without."),
             ("2026-04-04", "2026-05-19", "Breach",
              "6.58x against 4.75x: breach; 5.06x with $44M of projected "
              "savings.")])

    def test_each_steps_figures_match_the_case_page_api(self):
        for step in rewind()["steps"]:
            with self.subTest(period=step["period_end"]):
                body = period(step)
                scenarios = body.get("scenarios") or []
                if scenarios:
                    lev = next(s for s in scenarios if not s["savings"])[
                        "net_leverage"]
                    best = max(scenarios, key=lambda s: s["savings"])
                    self.assertIn(
                        f"{best['net_leverage']['ratio_2dp']:.2f}x",
                        step["verdict"])
                else:
                    lev = body["net_leverage"]
                self.assertEqual(step["ratio_2dp"], lev["ratio_2dp"])
                self.assertEqual(step["limit"], lev["threshold"])
                without = body.get("sensitivity_without_proforma")
                if without:
                    self.assertIn(
                        f"{without['net_leverage']['ratio_2dp']:.2f}x",
                        step["verdict"])

    def test_outlook_matches_the_projection_the_case_page_shows(self):
        steps = rewind()["steps"]
        self.assertIsNone(steps[0]["outlook"])
        for step in steps[1:]:
            with self.subTest(period=step["period_end"]):
                projection = period(step)["projection"]
                self.assertEqual(step["outlook"]["risk"],
                                 projection["risk"]["onya"])
                self.assertEqual(
                    step["outlook"]["ratio_2dp"],
                    projection["projections"]["onya"]["ratio_2dp"])
                self.assertEqual(step["outlook"]["limit"],
                                 projection["next_threshold"])

    def test_no_step_uses_a_filing_after_its_as_of_date(self):
        facts = xbrl.load_facts()["facts"]
        for step in rewind()["steps"]:
            with self.subTest(period=step["period_end"]):
                as_of = step["as_of"]
                self.assertLessEqual(step["governing"]["filed"], as_of)
                result = period(step)
                for component in result["components"]:
                    source = str(component["source"])
                    if not source.startswith("xbrl:"):
                        continue
                    _, namespace, name = source.split(":", 2)
                    filed = [
                        fact["filed"]
                        for unit in facts[namespace][name]["units"].values()
                        for fact in unit
                        if fact.get("end") == step["period_end"]]
                    self.assertLessEqual(min(filed), as_of, source)
                text = json.dumps(step).lower()
                for later in ("chapter 11", "fourteenth"):
                    self.assertNotIn(later, text)

    def test_a_step_never_shows_an_actual_from_after_its_test(self):
        # The projection file holds a back-test against later actuals.
        for step in rewind()["steps"]:
            self.assertNotIn("backtest", json.dumps(step))

    def test_events_are_dated_sec_links(self):
        events = rewind()["events"]
        self.assertEqual([e["date"] for e in events],
                         ["2026-04-28", "2026-06-12"])
        for event in events:
            self.assertTrue(event["url"].startswith("https://www.sec.gov/"))

    def test_other_companies_have_no_rewind(self):
        self.assertEqual(CLIENT.get("/company/AMCX/rewind").status_code, 404)


if __name__ == "__main__":
    unittest.main()
