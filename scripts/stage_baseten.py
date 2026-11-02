#!/usr/bin/env python3
"""Assemble the Baseten Truss staging directory for the Onya API.

Usage (from the repo root):
    .venv/bin/python scripts/stage_baseten.py [staging-dir]

Prints the file list and total size. The staging directory is what
`baseten model push --dir` uploads; it contains config.yaml,
requirements.txt, model/ (the app code, from src/), and only the data
the API reads at runtime. No .env, no web/, no tests, no data/runs,
and no other borrowers' raw filings.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIRS = ["results", "extracted", "backtest", "samples", "cache"]
RAW_PREFIXES = ("827187_", "snbr_")


def _copy_tree(src: Path, dest: Path, files: list[Path]) -> None:
    for path in sorted(src.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        out = dest / path.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        files.append(out)


def build_staging(staging: Path) -> list[Path]:
    """Copy exactly the runtime file set into `staging`; return files."""
    files: list[Path] = []
    staging.mkdir(parents=True, exist_ok=True)

    def place(src: Path, rel: str) -> None:
        out = staging / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        files.append(out)

    place(ROOT / "deploy" / "baseten" / "config.yaml", "config.yaml")
    place(ROOT / "requirements.txt", "requirements.txt")
    _copy_tree(ROOT / "src", staging / "model", files)
    for name in DATA_DIRS:
        _copy_tree(ROOT / "data" / name, staging / "data" / name, files)
    place(ROOT / "data" / "companies.json", "data/companies.json")
    raw_src = ROOT / "data" / "raw"
    for path in sorted(raw_src.iterdir()):
        if path.is_file() and path.name.startswith(RAW_PREFIXES):
            place(path, f"data/raw/{path.name}")
    return files


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    staging = Path(args[0]) if args else ROOT / "deploy" / "baseten" / "staging"
    files = build_staging(staging)
    total = sum(p.stat().st_size for p in files)
    print(f"Staged {len(files)} files, {total / 1e6:.1f} MB total in {staging}:")
    for path in files:
        print(f"  {path.relative_to(staging)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
