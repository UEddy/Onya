"""Focused tests for dash-cell handling in extract_release."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import extract_release


class DashPrompt(unittest.TestCase):
    def test_schema_mentions_printed_as_dash(self):
        self.assertIn("printed_as_dash", extract_release.SCHEMA)

    def test_instructions_require_zero_and_flag_for_dash(self):
        instructions = extract_release.INSTRUCTIONS
        self.assertIn("printed_as_dash", instructions)
        self.assertIn("value_thousands", instructions)
        for dash in ("—", "–", "-"):
            self.assertIn(dash, instructions)


class LineCellsContainDash(unittest.TestCase):
    def test_em_dash_found(self):
        doc = "Asset impairments\n—\n1,220\n—\n1,220\nAdjusted EBITDA\n"
        self.assertTrue(
            extract_release.line_cells_contain_dash(doc, "Asset impairments"))

    def test_en_dash_found(self):
        doc = "Some line\n–\n1,000\nNext label\n"
        self.assertTrue(
            extract_release.line_cells_contain_dash(doc, "Some line"))

    def test_hyphen_found(self):
        doc = "Some line\n-\n1,000\nNext label\n"
        self.assertTrue(
            extract_release.line_cells_contain_dash(doc, "Some line"))

    def test_no_dash_returns_false(self):
        doc = ("Finance lease obligations\n159\n241\n"
               "Consolidated funded indebtedness\n")
        self.assertFalse(
            extract_release.line_cells_contain_dash(
                doc, "Finance lease obligations"))

    def test_stops_at_next_label(self):
        # Dash belongs to Row B; Row A must not match by bleeding forward.
        doc = "Row A\n1,000\n2,000\nRow B\n—\n5,000\n"
        self.assertFalse(
            extract_release.line_cells_contain_dash(doc, "Row A"))
        self.assertTrue(
            extract_release.line_cells_contain_dash(doc, "Row B"))

    def test_missing_label_returns_false(self):
        self.assertFalse(
            extract_release.line_cells_contain_dash("Other\n—\n", "Nope"))


class NormalizePunctuationSpacing(unittest.TestCase):
    def assertVerifies(self, quote, source):
        norm = extract_release.normalize
        self.assertIn(norm(quote), norm(source))

    def test_trimas_spacing_variants_match(self):
        self.assertVerifies("December 31, 2024, to be less than",
                             "December 31, 2024 , to be less than")
        self.assertVerifies("$75,000,000 and 6.0%",
                             "$ 75,000,000 and 6.0 %")
        self.assertVerifies("Ratio.", "Ratio .")

    def test_different_amounts_do_not_match(self):
        norm = extract_release.normalize
        self.assertNotIn(norm("$7,500,000"), norm("$75,000,000"))

    def test_quote_spacing_matches(self):
        self.assertVerifies('" Consolidated EBITDA " means',
                             '"Consolidated EBITDA" means')


if __name__ == "__main__":
    unittest.main()
