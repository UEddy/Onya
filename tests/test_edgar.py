"""Focused regression test: edgar.main continues past a failed download."""

import io
import sys
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


if __name__ == "__main__":
    unittest.main()
