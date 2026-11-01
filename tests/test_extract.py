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


class DiagnoseFailedQuote(unittest.TestCase):
    def test_partial_match_reports_divergence(self):
        source = "the quick brown fox jumps"
        quote = "the quick brown fox leaps over"
        diag = extract.diagnose_failed_quote(quote, source)
        self.assertEqual(diag["matched_prefix_len"],
                         len("the quick brown fox "))
        self.assertEqual(diag["quote_next"], "leaps over")
        self.assertEqual(diag["source_context"], source)
        self.assertEqual(diag["source_pos"], 0)

    def test_repeated_content_finds_longest_prefix(self):
        diag = extract.diagnose_failed_quote("aaaaac", "aaaaab")
        self.assertEqual(diag["matched_prefix_len"], 5)
        self.assertEqual(diag["quote_next"], "c")
        self.assertEqual(diag["source_context"], "aaaaab")
        self.assertEqual(diag["source_pos"], 0)

    def test_zero_match_has_no_source_position(self):
        diag = extract.diagnose_failed_quote("zzz top", "abc def")
        self.assertEqual(diag["matched_prefix_len"], 0)
        self.assertEqual(diag["quote_next"], "zzz top")
        self.assertEqual(diag["source_context"], "")
        self.assertIsNone(diag["source_pos"])

    def test_context_window_is_60_chars(self):
        source = "prefix " + "s" * 200
        quote = "prefix " + "q" * 200
        diag = extract.diagnose_failed_quote(quote, source)
        self.assertEqual(diag["matched_prefix_len"], len("prefix "))
        self.assertEqual(diag["quote_next"], "q" * 60)
        self.assertEqual(diag["source_context"], "prefix " + "s" * 53)
        self.assertEqual(len(diag["source_context"]), 60)

    def test_compares_normalized_forms(self):
        source = extract.normalize("“Consolidated  EBITDA”\nmeans X")
        diag = extract.diagnose_failed_quote(
            '"Consolidated EBITDA" means Y', source)
        self.assertEqual(diag["matched_prefix_len"],
                         len('"Consolidated EBITDA"means '))
        self.assertEqual(diag["quote_next"], "Y")

    def test_non_string_quote_matches_nothing(self):
        diag = extract.diagnose_failed_quote(None, "abc")
        self.assertEqual(diag["matched_prefix_len"], 0)
        self.assertEqual(diag["quote_next"], "")
        self.assertIsNone(diag["source_pos"])

    def test_format_shows_key_fields(self):
        diag = extract.diagnose_failed_quote("aaaaac", "aaaaab")
        text = extract.format_diagnostic(diag, index=1)
        self.assertIn("5", text)
        self.assertIn("quote_next", text)
        self.assertIn("source_context", text)

    def test_empty_quote_has_empty_quote_reason(self):
        for quote in ("", "   ", None):
            diag = extract.diagnose_failed_quote(quote, "abc def")
            self.assertEqual(diag["reason"], "empty quote")
            self.assertEqual(diag["matched_prefix_len"], 0)
            self.assertIsNone(diag["source_pos"])

    def test_empty_quote_diagnostic_says_so(self):
        diag = extract.diagnose_failed_quote("", "abc def")
        text = extract.format_diagnostic(diag, index=1)
        self.assertIn("empty quote", text)
        self.assertNotIn("''", text)


class NormalizePunctuationSpacing(unittest.TestCase):
    def assertVerifies(self, quote, source):
        self.assertIn(extract.normalize(quote), extract.normalize(source))

    def test_comma_space_matches(self):
        self.assertVerifies("December 31, 2024, to be less than",
                             "December 31, 2024 , to be less than")

    def test_dollar_and_percent_space_match(self):
        self.assertVerifies("$75,000,000 and 6.0%",
                             "$ 75,000,000 and 6.0 %")

    def test_period_space_matches(self):
        self.assertVerifies("Ratio.", "Ratio .")

    def test_other_punctuation_spacing_matches(self):
        self.assertEqual(extract.normalize("a ( b ) ; c : d [ e ]"),
                         "a (b); c: d [e]")

    def test_quote_spacing_matches(self):
        self.assertVerifies('" Consolidated EBITDA " means',
                             '"Consolidated EBITDA" means')

    def test_words_and_digits_still_match_exactly(self):
        self.assertEqual(extract.normalize("December  31\n2024"),
                         "December 31 2024")
        self.assertEqual(extract.normalize("$75,000,000"), "$75,000,000")

    def test_different_amounts_do_not_match(self):
        self.assertNotIn(extract.normalize("$7,500,000"),
                         extract.normalize("$75,000,000"))
        self.assertNotIn(extract.normalize("$75,000,000"),
                         extract.normalize("$7,500,000"))


if __name__ == "__main__":
    unittest.main()
