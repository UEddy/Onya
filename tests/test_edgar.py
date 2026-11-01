"""Focused regression tests: edgar.main continues past failures; fetch retries."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import requests

import edgar


def _http_error(status):
    resp = SimpleNamespace(status_code=status)
    return requests.HTTPError(f"GET failed with status {status}", response=resp)


class MainContinuesOnFailure(unittest.TestCase):
    def test_failure_prints_filename_and_status_then_continues(self):
        files = [
            ("http://example.invalid/a", "a.htm"),
            ("http://example.invalid/b", "b.htm"),
            ("http://example.invalid/c", "c.htm"),
        ]
        calls = []

        def fake_fetch(url, filename):
            calls.append(filename)
            if filename == "b.htm":
                raise _http_error(404)
            return Path(__file__)  # existing file so stat() works

        with (
            patch.object(edgar, "FILES", files),
            patch.object(edgar, "fetch", side_effect=fake_fetch),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                edgar.main()
        out = buf.getvalue()

        self.assertEqual(calls, ["a.htm", "b.htm", "c.htm"])  # kept going past b.htm
        self.assertIn("b.htm", out)
        self.assertIn("404", out)
        self.assertIn("2 succeeded, 1 failed", out)


class FetchRetry(unittest.TestCase):
    def test_connection_error_retries_3_times_then_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(edgar, "RAW_DIR", Path(tmp)),
                  patch.object(edgar.requests, "get",
                               side_effect=requests.ConnectionError("dns fail")),
                  patch.object(edgar.time, "sleep") as sleep):
                with self.assertRaises(requests.ConnectionError):
                    edgar.fetch("http://example.invalid/a", "a.htm")
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(waits, [5, 15, 30])

    def test_recovers_after_transient_failures(self):
        ok = SimpleNamespace(status_code=200, content=b"data")
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(edgar, "RAW_DIR", Path(tmp)),
                  patch.object(
                      edgar.requests, "get",
                      side_effect=[requests.ConnectionError("down"),
                                    requests.ConnectionError("down"), ok]),
                  patch.object(edgar.time, "sleep") as sleep):
                dest = edgar.fetch("http://example.invalid/a", "a.htm")
            self.assertEqual(dest, Path(tmp) / "a.htm")
            self.assertEqual((Path(tmp) / "a.htm").read_bytes(), b"data")
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(waits, [5, 15, 0.5])

    def test_http_error_raises_without_retry(self):
        bad = SimpleNamespace(status_code=404, content=b"")
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(edgar, "RAW_DIR", Path(tmp)),
                  patch.object(edgar.requests, "get",
                               return_value=bad) as get,
                  patch.object(edgar.time, "sleep") as sleep):
                with self.assertRaises(requests.HTTPError):
                    edgar.fetch("http://example.invalid/a", "a.htm")
        get.assert_called_once()
        sleep.assert_not_called()

    def test_cached_file_returns_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.htm"
            dest.write_bytes(b"cached")
            with patch.object(edgar, "RAW_DIR", Path(tmp)), patch.object(
                    edgar.requests, "get",
                    side_effect=AssertionError("no network")) as get:
                self.assertEqual(
                    edgar.fetch("http://example.invalid/a", "a.htm"), dest)
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
