"""Tests for production runtime paths (overlay under /tmp, reads first).

Locally every runtime path lives under data/. In production the bundle
is read-only, so writes must land under the overlay and reads must
check the bundled file first.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import agent  # noqa: E402
import edgar  # noqa: E402
from runtime_paths import (bundled_path, overlay_root,  # noqa: E402
                           read_candidates, writable_path)


class OverlayRoot(unittest.TestCase):
    def test_local_has_no_overlay(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ONYA_ENV", None)
            os.environ.pop("ONYA_RUNTIME_DIR", None)
            self.assertIsNone(overlay_root())
            self.assertEqual(writable_path("runs"),
                             bundled_path("runs"))

    def test_production_uses_tmp(self):
        with patch.dict(os.environ, {"ONYA_ENV": "production",
                                     "ONYA_RUNTIME_DIR": ""}, clear=False):
            self.assertEqual(overlay_root(), Path("/tmp/onya"))
            self.assertEqual(writable_path("runs"),
                             Path("/tmp/onya/runs"))

    def test_explicit_dir_wins(self):
        with patch.dict(os.environ, {"ONYA_RUNTIME_DIR": "/tmp/x"}):
            self.assertEqual(overlay_root(), Path("/tmp/x"))

    def test_bundled_read_first(self):
        with patch.dict(os.environ, {"ONYA_RUNTIME_DIR": "/tmp/x"}):
            candidates = read_candidates("cache", "f.json")
        self.assertEqual(candidates[0], bundled_path("cache", "f.json"))
        self.assertEqual(candidates[1], Path("/tmp/x/cache/f.json"))


class ProductionWrites(unittest.TestCase):
    def test_select_cache_roundtrips_to_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"ONYA_ENV": "production", "ONYA_RUNTIME_DIR": tmp}
            with patch.dict(os.environ, env, clear=False):
                edgar._save_select_cache("0000827187", "2026-04-04",
                                         {"cik": "x"}, [])
                path = edgar._select_cache_read("0000827187",
                                                "2026-04-04")
            self.assertEqual(
                path, Path(tmp) / "cache" / "select_0000827187_2026-04-04.json")
            body = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(body["cik"], "0000827187")

    def test_agent_trace_dir_is_overlay_in_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"ONYA_ENV": "production", "ONYA_RUNTIME_DIR": tmp}
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(agent._runs_dir(), Path(tmp) / "runs")

    def test_no_production_write_escapes_overlay(self):
        written = []

        real_write = Path.write_text

        def spy(self, *args, **kwargs):
            written.append(self)
            return real_write(self, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            env = {"ONYA_ENV": "production", "ONYA_RUNTIME_DIR": tmp}
            with patch.dict(os.environ, env, clear=False):
                with patch.object(Path, "write_text", spy):
                    edgar._save_select_cache("0000000001", None,
                                             {"cik": "y"}, [])
        root = Path(tmp).resolve()
        for path in written:
            self.assertIn(root, path.resolve().parents,
                          f"write escaped overlay: {path}")


if __name__ == "__main__":
    unittest.main()
