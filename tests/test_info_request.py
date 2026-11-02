"""Tests for src/info_request.py (deterministic request builder)."""

import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import covenant  # noqa: E402
import edgar  # noqa: E402
import info_request  # noqa: E402
import project  # noqa: E402


def _inputs():
    compute_result = covenant.compute("2026-04-04")
    reviewed = json.loads(
        (PROJECT_ROOT / "data" / "extracted"
         / "snbr_covenants.reviewed.json").read_text(encoding="utf-8"))
    projection = project.compute("2026-04-04")
    base, amendments = edgar.select_agreement("827187",
                                              as_of="2026-05-19")
    agreement = {"base": dict(base),
                 "amendments": [dict(a) for a in amendments]}
    return compute_result, reviewed, projection, agreement


class Builder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.built = info_request.build_info_request(*_inputs())

    def test_five_items(self):
        self.assertEqual(len(self.built["items"]), 5)
        self.assertIn("Apr 4, 2026", self.built["subject"])

    def test_addback_item_tied_to_findings(self):
        first = self.built["items"][0]
        self.assertIn("(a)(iv)", first["text"])
        self.assertIn("(a)(viii)", first["text"])
        self.assertIn("$25 million", first["text"])
        self.assertIn("$18.7 million", first["why"])

    def test_savings_approval_item(self):
        second = self.built["items"][1]
        self.assertIn("(a)(ix)", second["text"])
        self.assertIn("$44 million", second["text"])
        self.assertIn("approval", second["text"].lower())

    def test_forecast_and_forbearance_items(self):
        texts = [item["text"] for item in self.built["items"]]
        self.assertTrue(any("Jul 4, 2026" in t for t in texts))
        self.assertTrue(any("forbearance expiry" in t.lower()
                            for t in texts))

    def test_reply_by_placeholder(self):
        self.assertEqual(self.built["reply_by"], "[lender to fill]")
        self.assertIn("[lender to fill]", self.built["request"])

    def test_every_figure_traces_to_inputs(self):
        compute_result, reviewed, projection, agreement = _inputs()
        haystack = json.dumps([compute_result, reviewed, projection,
                               agreement])
        for value in self.built["figures"]:
            self.assertIn(str(value).replace(".0", ""), haystack
                          .replace(".0", ""),
                          f"figure {value!r} not found in inputs")

    def test_every_rendered_number_traces_to_inputs(self):
        found = set(re.findall(r"\$[\d,]+(?:\.\d+)?(?: million)?"
                               r"|\d+\.\d+x", self.built["request"]))
        self.assertTrue(found)
        for token in found:
            if token.endswith(" million"):
                amount = float(token[1:-8].replace(",", "")) * 1e6
                self.assertTrue(
                    any(abs(float(v)) == amount or
                        abs(abs(float(v)) - amount) < 1e6
                        for v in self.built["figures"]),
                    f"{token} not traced")
            elif token.endswith("x"):
                everything = json.dumps([_inputs()[0], _inputs()[2]])
                self.assertTrue(
                    token in everything
                    or token.rstrip("x") in everything
                    or ("%sx" % float(token[:-1])) in everything,
                    f"{token} not traced")
            else:
                digits = token[1:].replace(",", "")
                self.assertTrue(
                    any(str(int(float(v))) == digits
                        or f"{float(v):,.0f}" == token[1:]
                        for v in self.built["figures"]),
                    f"{token} not traced")

    def test_no_breach_no_request(self):
        passing = dict(_inputs()[0])
        passing["net_leverage"] = dict(passing["net_leverage"], **{"pass": True})
        passing["interest_coverage"] = dict(
            passing["interest_coverage"], **{"pass": True})
        low_risk = dict(_inputs()[2], risk={"onya": "LOW"})
        built = info_request.build_info_request(
            passing, _inputs()[1], low_risk, _inputs()[3])
        self.assertIsNone(built["request"])


if __name__ == "__main__":
    unittest.main()
