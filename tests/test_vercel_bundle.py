"""Bundle audit for the onya-api Vercel project (no deploy happens).

Vercel uploads git-tracked files minus vercel.json's excludeFiles.
This test mirrors that exactly (git ls-files plus the exclusion),
then asserts the runtime file set is what the API reads (src code,
the data subset from the earlier audit, entrypoint, config,
requirements) and the total stays far under the 500 MB uncompressed
Python limit.
"""

import fnmatch
import json
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Must stay under 500 MB with a wide margin.
SIZE_BUDGET = 100_000_000

RAW_PREFIXES = ("827187_", "snbr_")
# Trimmed SEC list behind GET /company/SNBR/filings-since.
FILINGS_SINCE_SNAPSHOT = "submissions_CIK0000827187.filings_since.json"


def _excludes():
    config = json.loads((PROJECT_ROOT / "vercel.json").read_text())
    raw = config["functions"]["app.py"]["excludeFiles"]
    assert raw.startswith("{") and raw.endswith("}"), raw
    return [part for part in raw[1:-1].split(",") if part]


def _bundle_files():
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True).stdout.split("\0")
    excludes = _excludes()
    found = []
    for text in sorted(t for t in tracked if t):
        if any(fnmatch.fnmatch(text, pat)
               or fnmatch.fnmatch(text, pat.rstrip("/**") + "/*")
               for pat in excludes):
            continue
        found.append(PROJECT_ROOT / text)
    return found


class BundleAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = _bundle_files()
        cls.rel = {p.relative_to(PROJECT_ROOT).as_posix()
                   for p in cls.files}

    def test_entrypoint_and_config(self):
        for name in ("app.py", "vercel.json", "requirements.txt"):
            self.assertIn(name, self.rel)

    def test_src_code_present(self):
        for name in ("src/api.py", "src/agent.py", "src/limits.py",
                     "src/runtime_paths.py", "src/secret_files.py",
                     "src/edgar.py"):
            self.assertIn(name, self.rel)

    def test_data_subset_present(self):
        self.assertIn("data/companies.json", self.rel)
        for prefix in ("data/results/", "data/extracted/",
                       "data/backtest/", "data/samples/"):
            self.assertTrue(
                any(n.startswith(prefix) for n in self.rel), prefix)
        raw = [n for n in self.rel if n.startswith("data/raw/")]
        self.assertTrue(raw, "Sleep Number raw subset must ship")
        self.assertIn(f"data/raw/{FILINGS_SINCE_SNAPSHOT}", self.rel)
        # What the information request and private check read for SNBR.
        for as_of in ("2025-11-11", "2026-02-17", "2026-05-19"):
            self.assertIn(
                f"data/cache/select_0000827187_{as_of}.json", self.rel)

    def test_raw_only_sleep_number(self):
        for name in self.rel:
            if name.startswith("data/raw/"):
                base = Path(name).name
                self.assertTrue(base.startswith(RAW_PREFIXES)
                                or base == FILINGS_SINCE_SNAPSHOT, name)

    def test_forbidden_absent(self):
        for name in self.rel:
            first = name.split("/")[0]
            self.assertNotIn(first, {"web", "tests", "deploy", "scripts"},
                             name)
            self.assertFalse(name.startswith("data/runs"), name)
        self.assertNotIn(".env", self.rel)
        self.assertNotIn("modal_app.py", self.rel)
        self.assertFalse(any(n.startswith("test_") and "/" not in n
                             for n in self.rel))

    def test_size_with_margin(self):
        total = sum(p.stat().st_size for p in self.files)
        self.assertLess(total, SIZE_BUDGET,
                        f"bundle is {total / 1e6:.1f} MB")


if __name__ == "__main__":
    unittest.main()
