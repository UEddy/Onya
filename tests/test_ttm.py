"""Focused regression tests: quarterly() prefers derived over differing direct."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import ttm


def _entry(direct_val, ytd_val):
    return {
        "units": {
            "USD": [
                {"start": "2025-01-01", "end": "2025-03-29",
                 "val": 100, "filed": "2025-04-01"},
                {"start": "2025-03-30", "end": "2025-06-28",
                 "val": direct_val, "filed": "2025-07-01"},
                {"start": "2025-01-01", "end": "2025-06-28",
                 "val": ytd_val, "filed": "2025-07-01"},
            ]
        }
    }


class QuarterlyDirectVsDerived(unittest.TestCase):
    def setUp(self):
        ttm.DATA_QUALITY_WARNINGS.clear()

    def tearDown(self):
        ttm.DATA_QUALITY_WARNINGS.clear()

    def test_mismatch_uses_derived_and_warns(self):
        with patch.object(ttm, "_entry", return_value=_entry(110, 250)):
            out = ttm.quarterly("us-gaap:TestConcept")
        self.assertEqual(out["2025-06-28"], 150)  # 250 - 100, not direct 110
        self.assertEqual(
            ttm.DATA_QUALITY_WARNINGS,
            [("us-gaap:TestConcept", "2025-06-28", 110, 150)],
        )

    def test_match_uses_direct_without_warning(self):
        with patch.object(ttm, "_entry", return_value=_entry(110, 210)):
            out = ttm.quarterly("us-gaap:TestConcept")
        self.assertEqual(out["2025-06-28"], 110)
        self.assertEqual(ttm.DATA_QUALITY_WARNINGS, [])


if __name__ == "__main__":
    unittest.main()
