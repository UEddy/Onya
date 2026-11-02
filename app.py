"""Vercel entrypoint for the onya-api project (Python/FastAPI preset).

Exposes the same ``app`` that ``uvicorn app:app`` serves locally, so
local runs and the deployed function share one entrypoint.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from api import app  # noqa: E402,F401  (re-exported for Vercel)
