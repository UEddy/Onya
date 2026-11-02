# Onya deploy runbook

Backend on Baseten as a Truss custom server, frontend on Vercel.
Do the steps in order. Nothing here contains a secret value; never
paste a secret into chat, git, or a file in this repo.

## How the pieces fit

- The browser only calls the Vercel origin. Read calls go to
  `/api/backend/...`, a server-side proxy that adds the Baseten key
  as `Authorization: Bearer`, and agent calls go through `/api/agent`.
  No backend URL or key is ever sent to the browser, and the build
  fails if `NEXT_PUBLIC_API_BASE` is set (web/scripts/check-env.mjs).
- Baseten serves the FastAPI app from the Truss staging directory
  (config: [deploy/baseten/config.yaml](deploy/baseten/config.yaml)).
  The build installs `requirements.txt` via the config's
  `requirements_file`, copies staging `model/` to `/app/model` and
  staging `data/` to `/app/data`, and mounts each `secrets:` entry
  at `/secrets/{name}`;
  [src/secret_files.py](src/secret_files.py) reads them at startup
  and falls back to the environment, so local runs are unchanged.
- Extra routes are reached at
  `https://model-<model_id>.api.baseten.co/environments/production/sync/<route>`;
  `ONYA_API_BASE` is that URL without a trailing slash, and the
  proxies join paths with [joinBackendUrl](web/lib/api.ts)
  (covered by [web/lib/backend-url.test.ts](web/lib/backend-url.test.ts)).

## 1. Create the Baseten secrets (Baseten website)

In workspace Settings, Secrets, add these keys (names only here;
values are yours):

- `META_API_KEY`
- `ONYA_DEMO_TOKEN` - generate a NEW production token, different
  from any local token. Run this, copy the output straight into the
  secret field, and do not print it anywhere else:

  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

  The same new token goes into Vercel in step 8.

- `SEC_USER_AGENT` - the SEC's fair-access rule requires a
  User-Agent naming a contact email (requests without one get 403).
  Value form: `OnyaDemo/1.0 you@example.com`. The container refuses
  to start in production when it is missing or has no `@`.

## 2. Install the CLI and log in (your WSL terminal)

The `baseten` command is a binary, not a pip package. Install the
Linux build and log in (browser login; nothing secret is stored in
the repo):

```bash
cd /home/eddy/dev/onya
release_url=$(curl -fsSL -o /dev/null -w '%{url_effective}' \
  https://github.com/basetenlabs/baseten-cli/releases/latest)
version=${release_url##*/}
curl -fsSL "https://github.com/basetenlabs/baseten-cli/releases/download/${version}/baseten_${version#v}_linux_amd64.tar.gz" \
  | tar xz -C ~/.local/bin baseten
export PATH="$HOME/.local/bin:$PATH"
baseten version
baseten auth login
```

## 3. Stage (your WSL terminal)

```bash
.venv/bin/python scripts/stage_baseten.py
```

The script prints the file list and total size (about 47 MB).
Check it: config.yaml, requirements.txt, model/, and only the data
the API reads at runtime. No .env, no web/, no tests, no data/runs.
The staging directory is git-ignored; re-stage after every backend
change.

## 4. Push the published deployment (your WSL terminal)

Push straight into the production environment (every model has one)
as a published deployment - never `--develop`:

```bash
baseten model push --dir deploy/baseten/staging \
  --environment production \
  --deployment-name onya-api \
  --min-replica 1 --max-replica 1 \
  --concurrency-target 16 \
  --wait --tail
```

- `--min-replica 1 --max-replica 1`: exactly one replica, always
  warm. This is required, not just cheaper: run state, rate limits
  and the token budget live in server memory, so a second replica
  would split them and a scale-to-zero would wipe them.
- `--concurrency-target 16`: one replica serves the landing page's
  six parallel reads plus agent polling without queueing.
- Cost: cpu 1 / 2 GiB lands on the `1x2` CPU instance at
  $0.00058/min (about $0.035/hr, about $25/month always on).

## 5. Note the model id (push output, then Baseten website)

`--wait` prints the model and deployment ids. The model id is also
in the model page URL (`app.baseten.co/models/<model_id>/...`).
Build the backend base URL from it (no trailing slash):

```text
https://model-<model_id>.api.baseten.co/environments/production/sync
```

## 6. Create the scoped invoke key (your WSL terminal, then website)

After the first push (it needs the model id), create a key that can
only call this model - never a personal key or a Manage key:

```bash
baseten org api-key create --type workspace-invoke \
  --name onya-site-prod --model-id <model_id>
```

Copy the key immediately; it is shown once. Then, in the dashboard
under Organization settings, API keys, restrict it with Environment
access to the production environment only. It goes only into
Vercel's `BASETEN_API_KEY` in step 8.

## 7. Health check (your WSL terminal)

The key is read hidden and never echoed:

```bash
ONYA_API_BASE=https://model-<model_id>.api.baseten.co/environments/production/sync
read -rs BASETEN_API_KEY && export BASETEN_API_KEY
curl -s -H "Authorization: Bearer $BASETEN_API_KEY" "$ONYA_API_BASE/health"
```

It should answer `{"status":"ok"}`. Without the header the gateway
answers 401.

## 8. Import the site and set env vars (Vercel dashboard)

Import the GitHub repo in Vercel. In the GitHub app settings, give
Vercel access to the Onya repo only. Set the root directory to
`web/`. Framework preset: Next.js.

Add these to the Production environment only.
Server-only (never prefix these with NEXT_PUBLIC):

- `ONYA_API_BASE` = the sync base URL from step 5
- `ONYA_DEMO_TOKEN` = the NEW production token from step 1
- `BASETEN_API_KEY` = the scoped invoke key from step 6

Public:

- `NEXT_PUBLIC_REPO_URL` = the public GitHub repo URL (optional; the
  footer GitHub link hides itself when unset)

Do NOT set `NEXT_PUBLIC_API_BASE`; the prebuild check fails on
purpose if it (or any `NEXT_PUBLIC_` name containing TOKEN, KEY or
SECRET) is present. Deploy from the dashboard.

## 9. Point production CORS at the site (repo, then WSL terminal)

In [deploy/baseten/config.yaml](deploy/baseten/config.yaml), set
`ONYA_FRONTEND_ORIGIN` to the Vercel URL (for example
https://onya.vercel.app), then re-stage and re-push (steps 3-4).
The browser never calls Baseten directly, so this only governs
direct API callers; `https://placeholder.invalid` keeps it closed
meanwhile.

## 10. Smoke test (your WSL terminal)

```bash
scripts/smoke_prod.sh https://model-<model_id>.api.baseten.co/environments/production/sync https://<site-url>
```

The script asks for the invoke key with hidden input. All lines
should say OK. Then open the site, run the agent once on
Sleep Number, and follow a memo figure link.

## Roll back

- Baseten: in the console, promote the previous `onya-api`
  deployment back into production
  (`baseten model deployment promote --model-id <model_id> --deployment-id <previous>`),
  or re-stage and re-push from a checkout of the last good commit.
- Vercel: in the dashboard, open Deployments and promote the previous
  production deployment.

## Kill switch and budget

- Pause the live agent: set `ONYA_AGENT_ENABLED` to 0 in the
  `environment_variables` of
  [deploy/baseten/config.yaml](deploy/baseten/config.yaml) and
  re-push (steps 3-4). `POST /agent/run` returns 503 and the site
  shows "The live agent is paused. See a saved run." Set it back to
  1 to resume.
- Daily token budget: `ONYA_DAILY_TOKEN_BUDGET` in the same place
  (default 1500000). When the day's recorded tokens reach it,
  `POST /agent/run` returns 429 and the site shows the saved-run
  fallback.

## Appendix: other backend targets

Baseten above is the production default. Two alternatives stay in
the repo; on either, still set `BASETEN_API_KEY` in Vercel to a
placeholder value (the `/api/backend` proxy requires it to be
non-empty; these upstreams ignore the extra header):

- Hugging Face Docker Space: [deploy/hf/Dockerfile](deploy/hf/Dockerfile)
  plus `scripts/deploy_hf.py <space-id>` uploads the same runtime
  file set (needs `huggingface_hub` from requirements-deploy.txt).
  Free Spaces sleep without traffic; the site shows a waking-up
  notice with a Retry button meanwhile.
- Modal: `modal_app.py`. Install the Modal CLI into .venv, run
  `modal setup`, create one Modal secret named `onya-prod` with the
  same key names as step 1 (including `ONYA_ENV=production` and the
  real `ONYA_FRONTEND_ORIGIN`), then
  `.venv/bin/modal deploy modal_app.py`, and point the Vercel env
  vars at the Modal web endpoint URL instead of the sync base URL.
