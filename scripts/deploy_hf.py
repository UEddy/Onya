#!/usr/bin/env python3
"""Assemble the Onya API file set and upload it to a Hugging Face Space.

Usage (from the repo root, after `hf auth login` or `huggingface-cli
login`):  .venv/bin/python scripts/deploy_hf.py UEddy/onya-api [--yes]

The upload uses the token huggingface_hub already stored from your
login. This script never takes, prints, or reads a token itself.
"""

import argparse
import shutil
import sys
import tempfile
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

    place(ROOT / "deploy" / "hf" / "Dockerfile", "Dockerfile")
    place(ROOT / "deploy" / "hf" / "README.md", "README.md")
    place(ROOT / "requirements.txt", "requirements.txt")
    _copy_tree(ROOT / "src", staging / "src", files)
    for name in DATA_DIRS:
        _copy_tree(ROOT / "data" / name, staging / "data" / name, files)
    place(ROOT / "data" / "companies.json", "data/companies.json")
    raw_src = ROOT / "data" / "raw"
    for path in sorted(raw_src.iterdir()):
        if path.is_file() and path.name.startswith(RAW_PREFIXES):
            place(path, f"data/raw/{path.name}")
    return files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("space", help="Space id, for example UEddy/onya-api")
    parser.add_argument("--yes", action="store_true",
                        help="upload without asking for confirmation")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="onya-hf-") as tmp:
        staging = Path(tmp) / "staging"
        files = build_staging(staging)
        total = sum(p.stat().st_size for p in files)
        print(f"Staged {len(files)} files, {total / 1e6:.1f} MB total:")
        for path in files:
            print(f"  {path.relative_to(staging)}")
        if not args.yes:
            answer = input(f"Upload to {args.space}? [y/N] ").strip().lower()
            if answer != "y":
                print("Not uploaded.")
                return 0
        from huggingface_hub import HfApi

        HfApi().upload_folder(
            repo_id=args.space,
            repo_type="space",
            folder_path=str(staging),
        )
        print(f"Uploaded to https://huggingface.co/spaces/{args.space}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
