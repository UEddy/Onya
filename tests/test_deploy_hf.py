"""Staging-set tests for scripts/deploy_hf.py (no upload happens)."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_deploy_module():
    spec = importlib.util.spec_from_file_location(
        "deploy_hf", PROJECT_ROOT / "scripts" / "deploy_hf.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_hf"] = module
    spec.loader.exec_module(module)
    return module


class StagingSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deploy = _load_deploy_module()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.staging = Path(cls._tmp.name) / "staging"
        cls.files = cls.deploy.build_staging(cls.staging)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def rel(self):
        return [str(p.relative_to(self.staging)) for p in self.files]

    def test_has_dockerfile_readme_requirements(self):
        names = set(self.rel())
        self.assertIn("Dockerfile", names)
        self.assertIn("README.md", names)
        self.assertIn("requirements.txt", names)

    def test_no_env_web_or_tests(self):
        for name in self.rel():
            self.assertNotIn(".env", Path(name).name)
            self.assertFalse(name.startswith("web/"), name)
            self.assertFalse(name.startswith("tests/"), name)

    def test_no_runs_dir(self):
        self.assertFalse(
            any(n.startswith("data/runs") for n in self.rel()))

    def test_raw_only_sleep_number(self):
        raw = [n for n in self.rel() if n.startswith("data/raw/")]
        self.assertTrue(raw)
        for name in raw:
            base = Path(name).name
            self.assertTrue(
                base.startswith("827187_") or base.startswith("snbr_"),
                name)

    def test_runtime_dirs_present(self):
        prefixes = ("src/", "data/results/", "data/extracted/",
                    "data/backtest/", "data/samples/", "data/cache/")
        names = self.rel()
        for prefix in prefixes:
            self.assertTrue(
                any(n.startswith(prefix) for n in names), prefix)
        self.assertIn("data/companies.json", names)


if __name__ == "__main__":
    unittest.main()
