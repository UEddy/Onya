"""Focused tests for the covenant extraction schema and prompt."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import extract


class EquityCureSchema(unittest.TestCase):
    def test_schema_has_equity_cure_object(self):
        self.assertIn("equity_cure", extract.SCHEMA)
        for key in ("present", "section", "max_uses", "limits",
                    "how_applied", "quote"):
            self.assertIn(key, extract.SCHEMA)

    def test_prompt_states_present_false_rule(self):
        self.assertIn(
            "set present=false only if the agreement contains no equity "
            "cure, cure right, or specified equity contribution provision",
            extract.INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
