"""Focused tests for src/score_disclosed.py."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import score_disclosed


def _key_cov(name, direction, threshold, actual, **extra):
    cov = {"name": name, "direction": direction,
           "threshold": threshold, "actual": actual}
    cov.update(extra)
    return cov


def _ext_cov(name, direction, threshold, actual, **extra):
    cov = {"name": name, "direction": direction,
           "threshold": threshold, "actual": actual,
           "in_compliance": True, "waiver_or_amendment_note": None,
           "quote": "q"}
    cov.update(extra)
    return cov


class NumbersMatch(unittest.TestCase):
    def test_exact_and_int_float_equal(self):
        self.assertTrue(score_disclosed.numbers_match(2.29, 2.29))
        self.assertTrue(score_disclosed.numbers_match(2.2, 2.20))
        self.assertTrue(score_disclosed.numbers_match(5.0, 5))

    def test_tolerance_boundary(self):
        self.assertTrue(score_disclosed.numbers_match(2.29, 2.30))
        self.assertFalse(score_disclosed.numbers_match(2.29, 2.31))

    def test_null_matches_null_only(self):
        self.assertTrue(score_disclosed.numbers_match(None, None))
        self.assertFalse(score_disclosed.numbers_match(None, 1.1))
        self.assertFalse(score_disclosed.numbers_match(1.1, None))

    def test_bool_is_not_a_number(self):
        self.assertFalse(score_disclosed.numbers_match(True, 1))


class ThresholdMatch(unittest.TestCase):
    def test_plain_match(self):
        key = _key_cov("total leverage", "max", 4.75, None)
        self.assertTrue(score_disclosed.threshold_match(
            _ext_cov("total leverage", "max", 4.75, None), key))

    def test_waived_alternative_accepted(self):
        key = _key_cov("debt service coverage", "min", 2.0, 1.99,
                       waived_threshold=1.75)
        self.assertTrue(score_disclosed.threshold_match(
            _ext_cov("debt service coverage", "min", 1.75, 1.99), key))
        self.assertTrue(score_disclosed.threshold_match(
            _ext_cov("debt service coverage", "min", 2.0, 1.99), key))
        self.assertFalse(score_disclosed.threshold_match(
            _ext_cov("debt service coverage", "min", 1.5, 1.99), key))


class MatchCovenants(unittest.TestCase):
    def test_ratio_suffix_ignored(self):
        key = [_key_cov("total net leverage", "max", 4.0, 2.29)]
        ext = [_ext_cov("Total Net Leverage Ratio", "max", 4.0, 2.29)]
        pairs, extras = score_disclosed.match_covenants(key, ext)
        self.assertEqual(pairs[0][1], ext[0])
        self.assertEqual(extras, [])

    def test_direction_must_agree(self):
        key = [_key_cov("leverage", "min", 3.0, 8.07)]
        ext = [_ext_cov("leverage", "max", 3.0, 8.07)]
        pairs, extras = score_disclosed.match_covenants(key, ext)
        self.assertIsNone(pairs[0][1])
        self.assertEqual(extras, ext)

    def test_hain_secured_vs_total_disambiguated(self):
        key = [_key_cov("secured leverage", "max", 5.5, 4.81),
               _key_cov("total leverage", "max", 6.0, 4.81)]
        ext = [_ext_cov("Total Leverage Ratio", "max", 6.0, 4.81),
               _ext_cov("Secured Leverage Ratio", "max", 5.5, 4.81)]
        pairs, extras = score_disclosed.match_covenants(key, ext)
        self.assertEqual(pairs[0][1]["threshold"], 5.5)
        self.assertEqual(pairs[1][1]["threshold"], 6.0)
        self.assertEqual(extras, [])

    def test_unmatched_key_and_extra_reported(self):
        key = [_key_cov("total leverage", "max", 4.25, 3.16)]
        ext = [_ext_cov("unrelated dividend test", "max", 1.0, 0.5)]
        pairs, extras = score_disclosed.match_covenants(key, ext)
        self.assertIsNone(pairs[0][1])
        self.assertEqual(extras, ext)


class ScoreCompany(unittest.TestCase):
    def test_full_match_flags(self):
        key_entry = {"covenants": [
            _key_cov("total leverage", "max", 4.25, 3.16)]}
        ext = {"covenants": [
            _ext_cov("Total Leverage Ratio", "max", 4.25, 3.16)]}
        rows, extras = score_disclosed.score_company("STGW", key_entry, ext)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["actual_match"])
        self.assertTrue(rows[0]["threshold_match"])
        self.assertEqual(extras, [])

    def test_missing_extraction_all_miss(self):
        key_entry = {"covenants": [
            _key_cov("total leverage", "max", 4.25, 3.16),
            _key_cov("fixed charge coverage", "min", 1.1, None)]}
        rows, _ = score_disclosed.score_company("STGW", key_entry, None)
        for row in rows:
            self.assertFalse(row["actual_match"])
            self.assertFalse(row["threshold_match"])

    def test_optx_null_actual_matches(self):
        key_entry = {"covenants": [
            _key_cov("fixed charge coverage", "min", 1.1, None)]}
        ext = {"covenants": [
            _ext_cov("Fixed Charge Coverage Ratio", "min", 1.1, None)]}
        rows, _ = score_disclosed.score_company("OPTX", key_entry, ext)
        self.assertTrue(rows[0]["actual_match"])
        self.assertTrue(rows[0]["threshold_match"])


class MatchedVerified(unittest.TestCase):
    def test_verified_match_counts_as_both(self):
        key_entry = {"covenants": [
            _key_cov("total leverage", "max", 4.25, 3.16)]}
        ext = {"covenants": [
            _ext_cov("Total Leverage Ratio", "max", 4.25, 3.16,
                     quote_verified=True)]}
        rows, _ = score_disclosed.score_company("STGW", key_entry, ext)
        self.assertTrue(rows[0]["matched"])
        self.assertTrue(rows[0]["verified"])
        self.assertTrue(rows[0]["matched_and_verified"])

    def test_unverified_match_does_not_count_as_verified(self):
        key_entry = {"covenants": [
            _key_cov("total leverage", "max", 4.25, 3.16)]}
        ext = {"covenants": [
            _ext_cov("Total Leverage Ratio", "max", 4.25, 3.16,
                     quote_verified=False)]}
        rows, _ = score_disclosed.score_company("STGW", key_entry, ext)
        self.assertTrue(rows[0]["matched"])
        self.assertFalse(rows[0]["verified"])
        self.assertFalse(rows[0]["matched_and_verified"])

    def test_missing_flag_is_unverified(self):
        key_entry = {"covenants": [
            _key_cov("total leverage", "max", 4.25, 3.16)]}
        ext = {"covenants": [
            _ext_cov("Total Leverage Ratio", "max", 4.25, 3.16)]}
        rows, _ = score_disclosed.score_company("STGW", key_entry, ext)
        self.assertTrue(rows[0]["matched"])
        self.assertFalse(rows[0]["verified"])
        self.assertFalse(rows[0]["matched_and_verified"])

    def test_partial_match_is_not_matched(self):
        key_entry = {"covenants": [
            _key_cov("total leverage", "max", 4.0, 2.29)]}
        ext = {"covenants": [
            _ext_cov("Total Leverage", "max", 4.0, 9.99,
                     quote_verified=True)]}
        rows, _ = score_disclosed.score_company("AAA", key_entry, ext)
        self.assertFalse(rows[0]["matched"])
        self.assertTrue(rows[0]["verified"])
        self.assertFalse(rows[0]["matched_and_verified"])

    def test_missing_extraction_all_false(self):
        key_entry = {"covenants": [
            _key_cov("total leverage", "max", 4.25, 3.16)]}
        rows, _ = score_disclosed.score_company("STGW", key_entry, None)
        self.assertFalse(rows[0]["matched"])
        self.assertFalse(rows[0]["verified"])
        self.assertFalse(rows[0]["matched_and_verified"])

    def test_unmatched_key_is_unverified(self):
        key_entry = {"covenants": [
            _key_cov("total leverage", "max", 4.25, 3.16)]}
        ext = {"covenants": [
            _ext_cov("unrelated dividend test", "max", 1.0, 0.5,
                     quote_verified=True)]}
        rows, _ = score_disclosed.score_company("STGW", key_entry, ext)
        self.assertFalse(rows[0]["matched"])
        self.assertFalse(rows[0]["verified"])
        self.assertFalse(rows[0]["matched_and_verified"])


class Main(unittest.TestCase):
    def _write(self, tmp, key, disclosed):
        tmp = Path(tmp)
        (tmp / "answer_key.json").write_text(json.dumps(key), encoding="utf-8")
        for ticker, payload in disclosed.items():
            (tmp / f"disclosed_{ticker}.json").write_text(
                json.dumps(payload), encoding="utf-8")
        return tmp

    def test_table_and_totals(self):
        key = {"AAA": {"covenants": [
                    _key_cov("total leverage", "max", 4.0, 2.29),
                    _key_cov("interest coverage", "min", 3.0, 8.07)]}}
        disclosed = {"AAA": {"period_end": "2025-09-30", "covenants": [
            _ext_cov("Total Leverage", "max", 4.0, 2.29),
            _ext_cov("Interest Coverage", "min", 3.0, 9.99)]}}
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = self._write(tmp, key, disclosed)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rows = score_disclosed.main(["score_disclosed.py"],
                                            backtest_dir=backtest_dir)
        out = buf.getvalue()
        self.assertEqual(len(rows), 2)
        self.assertIn("company", out)
        self.assertIn("actual ext vs key", out)
        self.assertIn("threshold ext vs key", out)
        self.assertIn("2.29 vs 2.29", out)
        self.assertIn("actual matched: 1/2", out)
        self.assertIn("threshold matched: 2/2", out)
        self.assertIn("fully matched: 1/2", out)

    def test_matched_verified_columns_and_totals(self):
        key = {"AAA": {"covenants": [
                    _key_cov("total leverage", "max", 4.0, 2.29),
                    _key_cov("interest coverage", "min", 3.0, 8.07),
                    _key_cov("fixed charge", "min", 1.1, 1.5)]}}
        disclosed = {"AAA": {"period_end": "2025-09-30", "covenants": [
            _ext_cov("Total Leverage", "max", 4.0, 2.29,
                     quote_verified=True),
            _ext_cov("Interest Coverage", "min", 3.0, 8.07,
                     quote_verified=False),
            _ext_cov("Fixed Charge", "min", 1.1, 9.99,
                     quote_verified=True)]}}
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = self._write(tmp, key, disclosed)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rows = score_disclosed.main(["score_disclosed.py"],
                                            backtest_dir=backtest_dir)
        out = buf.getvalue()
        self.assertEqual(len(rows), 2 + 1)
        self.assertIn("matched", out)
        self.assertIn("verified", out)
        self.assertIn("matched_and_verified", out)
        self.assertIn("matched: 2/3", out)
        self.assertIn("verified: 2/3", out)
        self.assertIn("matched_and_verified: 1/3", out)
        self.assertTrue(rows[0]["matched_and_verified"])
        self.assertTrue(rows[1]["matched"])
        self.assertFalse(rows[1]["matched_and_verified"])

    def test_missing_file_noted_and_missed(self):
        key = {"AAA": {"covenants": [
            _key_cov("total leverage", "max", 4.0, 2.29)]}}
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = self._write(tmp, key, {})
            buf = io.StringIO()
            with redirect_stdout(buf):
                rows = score_disclosed.main(["score_disclosed.py"],
                                            backtest_dir=backtest_dir)
        self.assertFalse(rows[0]["actual_match"])
        self.assertIn("no disclosed_AAA.json", buf.getvalue())
        self.assertIn("actual matched: 0/1", buf.getvalue())

    def test_unknown_ticker_exits_2(self):
        key = {"AAA": {"covenants": []}}
        with tempfile.TemporaryDirectory() as tmp:
            backtest_dir = self._write(tmp, key, {})
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    score_disclosed.main(["score_disclosed.py", "ZZZ"],
                                         backtest_dir=backtest_dir)
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
