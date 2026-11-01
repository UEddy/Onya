"""Focused tests for the xbrl/ttm CIK generalization (mocked downloads)."""

import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import ttm
import xbrl

OTHER_CIK = "842633"
OTHER_CIK10 = "0000842633"
OTHER_URL = ("https://data.sec.gov/api/xbrl/companyfacts/"
             "CIK0000842633.json")
OTHER_FILE = "companyfacts_0000842633.json"


def _facts_doc():
    return {"facts": {"us-gaap": {"Cash": {"label": "cash", "units": {}}}}}


def _write_tmp(tmp, name="facts.json"):
    path = Path(tmp) / name
    path.write_text(json.dumps(_facts_doc()), encoding="utf-8")
    return str(path)


class LoadFacts(unittest.TestCase):
    def test_default_path_unchanged(self):
        self.assertEqual(xbrl.DEFAULT_PATH, "data/raw/snbr_companyfacts.json")

    def test_default_loads_snbr_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tmp(tmp)
            with patch.object(xbrl, "DEFAULT_PATH", path):
                self.assertEqual(xbrl.load_facts(), _facts_doc())

    def test_snbr_cik_uses_snbr_path_without_download(self):
        fake = SimpleNamespace(
            fetch=unittest.mock.Mock(
                side_effect=AssertionError("must not download SNBR")))
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tmp(tmp)
            with (patch.object(xbrl, "DEFAULT_PATH", path),
                  patch.dict(sys.modules, {"edgar": fake})):
                for cik in ("827187", "0000827187", 827187):
                    self.assertEqual(xbrl.load_facts(cik=cik), _facts_doc())
        fake.fetch.assert_not_called()

    def test_other_cik_downloads_via_edgar_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cached = _write_tmp(tmp, OTHER_FILE)
            fetch = unittest.mock.Mock(return_value=Path(cached))
            fake = SimpleNamespace(fetch=fetch)
            with patch.dict(sys.modules, {"edgar": fake}):
                self.assertEqual(xbrl.load_facts(cik=OTHER_CIK), _facts_doc())
        fetch.assert_called_once_with(OTHER_URL, OTHER_FILE)

    def test_explicit_path_wins_over_cik(self):
        fake = SimpleNamespace(
            fetch=unittest.mock.Mock(
                side_effect=AssertionError("must not download")))
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tmp(tmp)
            with patch.dict(sys.modules, {"edgar": fake}):
                self.assertEqual(
                    xbrl.load_facts(path=path, cik=OTHER_CIK), _facts_doc())
        fake.fetch.assert_not_called()

    def test_invalid_cik_raises(self):
        with self.assertRaises(ValueError):
            xbrl.load_facts(cik="not-a-cik")

    def test_companyfacts_filename(self):
        self.assertEqual(xbrl.companyfacts_filename(OTHER_CIK), OTHER_FILE)
        self.assertEqual(xbrl.companyfacts_filename(OTHER_CIK10), OTHER_FILE)


class PassThrough(unittest.TestCase):
    def test_list_candidates_and_show_pass_cik(self):
        with patch.object(xbrl, "load_facts", return_value={"facts": {}}) \
                as load:
            buf = io.StringIO()
            with redirect_stdout(buf):
                xbrl.list_candidates(["cash"], cik=OTHER_CIK)
                xbrl.show("us-gaap:Cash", cik=OTHER_CIK)
                xbrl.list_candidates(["cash"])
        calls = [c.kwargs.get("cik") for c in load.call_args_list]
        self.assertEqual(calls, [OTHER_CIK, OTHER_CIK, None])

    def test_ttm_forwards_cik(self):
        entry = {"units": {"USD": [{"end": "2025-09-30", "val": 5,
                                    "filed": "2025-10-01", "form": "10-Q"}]}}
        with patch.object(ttm, "_entry", return_value=entry) as mocked:
            ttm.quarterly("us-gaap:X", cik=OTHER_CIK)
            ttm.instant("us-gaap:X", "2025-09-30", cik=OTHER_CIK)
        for call in mocked.call_args_list:
            self.assertEqual(call.kwargs.get("cik"), OTHER_CIK)

    def test_ttm_default_cik_is_none(self):
        entry = {"units": {"USD": [{"end": "2025-09-30", "val": 5,
                                    "filed": "2025-10-01", "form": "10-Q"}]}}
        with patch.object(ttm, "_entry", return_value=entry) as mocked:
            ttm.quarterly("us-gaap:X")
            ttm.instant("us-gaap:X", "2025-09-30")
        for call in mocked.call_args_list:
            self.assertEqual(call.args[1:], ())
            self.assertIsNone(call.kwargs.get("cik"))


if __name__ == "__main__":
    unittest.main()
