"""Onya API on Modal. Deploy with: modal deploy modal_app.py

Run state choice: the app is pinned to ONE container (max_containers=1)
with concurrent inputs. Run records, traces, rate-limit counters and the
daily token ledger live in process memory and on the container disk, so
pinning guarantees GET /agent/run/{id} polling always finds its run.
The alternative (modal.Dict plus a Volume for traces) adds two stores
and a sync problem for a demo workload of at most 30 runs a day; if
traffic ever needs more than one container, that is the migration to
make first. A container restart loses in-flight runs only.

The image is read-only in intent: it carries src/ and only the data the
API and agent read at runtime. Agent traces are written by the running
container to its ephemeral disk under data/runs, never to the image.
Secrets come from the Modal secret named "onya-prod"; nothing is read
from ~/.config/onya/.env in production (the production guards in
src/api.py refuse to start without the required environment).
"""

from pathlib import Path

import modal

ROOT = Path(__file__).parent

app = modal.App("onya")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements(str(ROOT / "requirements.txt"))
    .add_local_dir(str(ROOT / "src"), "/root/onya/src", copy=True,
                   ignore=["__pycache__"])
    .add_local_dir(str(ROOT / "data" / "results"),
                   "/root/onya/data/results", copy=True)
    .add_local_dir(str(ROOT / "data" / "extracted"),
                   "/root/onya/data/extracted", copy=True)
    .add_local_dir(str(ROOT / "data" / "backtest"),
                   "/root/onya/data/backtest", copy=True)
    .add_local_dir(str(ROOT / "data" / "samples"),
                   "/root/onya/data/samples", copy=True)
    .add_local_dir(str(ROOT / "data" / "cache"),
                   "/root/onya/data/cache", copy=True)
    .add_local_file(str(ROOT / "data" / "companies.json"),
                    "/root/onya/data/companies.json", copy=True)
    # Only the cached Sleep Number filings the agent path reuses; other
    # borrowers' raw filings (about 169 MB) stay out of the image.
    .add_local_dir(str(ROOT / "data" / "raw"), "/root/onya/data/raw",
                   copy=True, ignore=["*", "!827187_*", "!snbr_*"])
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("onya-prod")],
    max_containers=1,
    timeout=900,
    scaledown_window=300,
)
@modal.asgi_app()
def fastapi_app():
    import os
    import sys

    os.chdir("/root/onya")
    sys.path.insert(0, "/root/onya/src")
    from api import app as onya_api

    return onya_api
