"""Writable runtime paths: bundled data is read-only on serverless.

Locally every path lives under data/. In production (ONYA_ENV=production,
e.g. Vercel) the bundle is read-only, so runtime writes go to an overlay
directory (/tmp/onya, or ONYA_RUNTIME_DIR when set for tests). Readers
check the bundled file first, then the overlay.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def overlay_root():
    """Writable overlay dir, or None when local paths are writable."""
    explicit = (os.environ.get("ONYA_RUNTIME_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    if (os.environ.get("ONYA_ENV") or "") == "production":
        return Path("/tmp/onya")
    return None


def bundled_path(*parts):
    """Read-only path inside the deployed bundle (data/... locally too)."""
    return PROJECT_ROOT / "data" / Path(*parts)


def writable_path(*parts):
    """Where a runtime file must be written (overlay in production)."""
    overlay = overlay_root()
    if overlay is not None:
        return overlay / Path(*parts)
    return bundled_path(*parts)


def read_candidates(*parts):
    """Bundled file first, then the overlay copy."""
    overlay = overlay_root()
    paths = [bundled_path(*parts)]
    if overlay is not None:
        paths.append(overlay / Path(*parts))
    return paths


def read_text_first(*parts):
    """Contents of the first candidate that exists, else None."""
    for path in read_candidates(*parts):
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return None
