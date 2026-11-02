"""Secret-file loader: /secrets/{name} wins, env falls back."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import secret_files  # noqa: E402


class SecretFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_file_wins_over_env(self):
        (self.dir / "META_API_KEY").write_text("from-file\n")
        with patch.object(secret_files, "SECRETS_DIR", self.dir):
            with patch.dict(os.environ, {"META_API_KEY": "from-env"}):
                self.assertEqual(
                    secret_files.get_secret("META_API_KEY"), "from-file")

    def test_env_fallback(self):
        with patch.object(secret_files, "SECRETS_DIR", self.dir):
            with patch.dict(os.environ, {"META_API_KEY": "from-env"}):
                self.assertEqual(
                    secret_files.get_secret("META_API_KEY"), "from-env")

    def test_load_sets_env_from_file(self):
        (self.dir / "META_API_KEY").write_text("meta-value")
        (self.dir / "ONYA_DEMO_TOKEN").write_text("token-value")
        env = {}
        with patch.object(secret_files, "SECRETS_DIR", self.dir):
            with patch.dict(os.environ, env, clear=True):
                secret_files.load_secret_files()
                self.assertEqual(os.environ["META_API_KEY"], "meta-value")
                self.assertEqual(os.environ["ONYA_DEMO_TOKEN"], "token-value")

    def test_missing_required_refused_in_production(self):
        with patch.object(secret_files, "SECRETS_DIR", self.dir):
            with patch.dict(os.environ, {"ONYA_ENV": "production"},
                            clear=True):
                with self.assertRaises(RuntimeError):
                    secret_files.load_secret_files()

    def test_missing_locally_is_silent(self):
        with patch.object(secret_files, "SECRETS_DIR", self.dir):
            with patch.dict(os.environ, {}, clear=True):
                secret_files.load_secret_files()


if __name__ == "__main__":
    unittest.main()
