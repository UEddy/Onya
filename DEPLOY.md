# Onya deploy runbook

Backend on Baseten as a Truss custom server, frontend on Vercel.
Do the steps in order. Nothing here contains a secret value; never
paste a secret into chat, git, or a file in this repo.

## How the pieces fit

- The browser only calls the Vercel origin. Read calls go to
  `/api/backend/...`, a server-side proxy that adds the Baseten
  `Api-Key` header; agent calls go through `/api/agent`. No backend
  URL or key is ever sent to the browser, and the build fails if
  `NEXT_PUBLIC_API_BASE` is set (web/scripts/check-env.mjs).
- Baseten serves the FastAPI app from the Truss staging directory
  (config: [deploy/baseten/config.yaml](deploy/baseten/config.yaml)).
  Baseten mounts the workspace secrets at `/secrets/{name}`;
  [src/secret_files.py](src/secret_files.py) reads them at startup
  and falls back to the environment, so local runs are unchanged.

## 1. Create the Baseten secrets (Baseten website)

Create a Baseten account, then in workspace Secrets add these keys
(names only here; values are yours):

- `META_API_KEY`
- `ONYA_DEMO_TOKEN`

Generate a NEW production `ONYA_DEMO_TOKEN`, different from any local
token. Run this, copy the output straight into the secret field, and
do not print it anywhere else:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

The same new token goes into Vercel in step 5. Also create a Baseten
API key for the Vercel proxy (step 5); it is not a workspace secret.

## 2. Install the deploy tools (your terminal)

```bash
cd /home/eddy/dev/onya
.venv/bin/pip install -r requirements-deploy.txt
.venv/bin/truss login
```

## 3. Stage and push (your terminal)

```bash
.venv/bin/python scripts/stage_baseten.py
.venv/bin/truss push deploy/baseten/staging
```

The staging script prints the file list and total size. Check it:
config.yaml, requirements.txt, src/, and only the data the API reads
at runtime. No .env, no web/, no tests, no data/runs. The staging
directory is git-ignored; re-stage after every backend change.

In the Baseten console, open the `onya-api` model and copy its invoke
URL (the production endpoint base). Check it is up:

```bash
curl -s https://<invoke-url>/health
```

Without an `Api-Key` header the gateway answers 401; that is expected
from a bare terminal. The site proxy in step 5 sends the key.

## 4. Import the site (Vercel dashboard)

Import the GitHub repo in Vercel. In the GitHub app settings, give
Vercel access to the Onya repo only. Set the root directory to `web/`.
Framework preset: Next.js.

## 5. Set the Vercel env vars (Vercel dashboard, Production only)

Server-only (never prefix these with NEXT_PUBLIC):

- `ONYA_API_BASE` = the Baseten invoke URL from step 3
- `ONYA_DEMO_TOKEN` = the NEW production token from step 1
- `BASETEN_API_KEY` = the Baseten API key from step 1

Public:

- `NEXT_PUBLIC_REPO_URL` = the public GitHub repo URL (optional; the
  footer GitHub link hides itself when unset)

Do NOT set `NEXT_PUBLIC_API_BASE`; the prebuild check fails on
purpose if it (or any `NEXT_PUBLIC_` name containing TOKEN, KEY or
SECRET) is present. Deploy from the dashboard.

## 6. Point production CORS at the site (repo, then re-push)

In [deploy/baseten/config.yaml](deploy/baseten/config.yaml), set
`ONYA_FRONTEND_ORIGIN` to the Vercel URL (for example
https://onya.vercel.app), then re-stage and re-push (step 3). The
browser never calls Baseten directly, so this only governs direct
API callers; `https://placeholder.invalid` keeps it closed meanwhile.

## 7. Smoke test (your terminal)

```bash
scripts/smoke_prod.sh https://<invoke-url> https://<site-url>
```

All lines should say OK. Then open the site, run the agent once on
Sleep Number, and follow a memo figure link.

## Roll back

- Baseten: in the console, promote the previous `onya-api`
  deployment, or re-stage and re-push from a checkout of the last
  good commit.
- Vercel: in the dashboard, open Deployments and promote the previous
  production deployment.

## Kill switch and budget

- Pause the live agent: set `ONYA_AGENT_ENABLED` to 0 in the
  `environment_variables` of
  [deploy/baseten/config.yaml](deploy/baseten/config.yaml) and
  re-push. `POST /agent/run` returns 503 and the site shows "The live
  agent is paused. See a saved run." Set it back to 1 to resume.
- Daily token budget: `ONYA_DAILY_TOKEN_BUDGET` in the same place
  (default 1500000). When the day's recorded tokens reach it,
  `POST /agent/run` returns 429 and the site shows the saved-run
  fallback.

## Appendix: other backend targets

The Baseten path above is the production default. Two alternatives
stay in the repo; on either, still set `BASETEN_API_KEY` in Vercel to
a placeholder value (the `/api/backend` proxy requires it to be
non-empty; these upstreams ignore the extra header):

- Hugging Face Docker Space: [deploy/hf/Dockerfile](deploy/hf/Dockerfile)
  plus `scripts/deploy_hf.py <space-id>` uploads the same runtime
  file set. Free Spaces sleep without traffic; the site shows a
  waking-up notice with a Retry button meanwhile.
- Modal: `modal_app.py`. Install the Modal CLI into .venv, run
  `modal setup`, create one Modal secret named `onya-prod` with the
  same key names as step 1 (including `ONYA_ENV=production` and the
  real `ONYA_FRONTEND_ORIGIN`), then
  `.venv/bin/modal deploy modal_app.py`, and point the Vercel env
  vars at the Modal web endpoint URL instead of the Baseten URL.
