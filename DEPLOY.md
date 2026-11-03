# Onya deploy runbook

Two Vercel projects from one repo: `onya-api` (Python/FastAPI,
repo root) and the site (Next.js, `web/`). The browser only calls
the site origin; the site proxies reads and streams agent runs from
`onya-api`. Do the steps in order. Nothing here contains a secret
value; never paste a secret into chat, git, or a file in this repo.

## How the pieces fit

- `onya-api` is one Python function: [app.py](app.py) re-exports the
  FastAPI `app`, and [vercel.json](vercel.json) pins the function to
  `maxDuration: 300` with an explicit `excludeFiles` list. The bundle
  is git-tracked files minus those excludes: entrypoint, config,
  requirements, `src/`, and the audited data subset
  ([tests/test_vercel_bundle.py](tests/test_vercel_bundle.py) enforces
  this and the sub-100 MB size, far under the 500 MB limit).
- `POST /agent/run` streams the run inside the request as
  newline-delimited JSON (`run_start`/`tool_call` step events, then
  exactly one `run_result` or `error`; `POST /private/compare` works
  the same way, ending in `private_result` or `error`). There is no
  polling: `GET /agent/run/{id}` answers 404. The run stops with a
  clear `took_too_long` result at 270 s, before the 300 s function cap.
- During a run the stream sends a `heartbeat` every 10 s of silence.
  Model calls ([src/model_calls.py](src/model_calls.py)) have a 90 s
  limit that fits inside the time left, and at most one retry, sent to
  the page as `model_retry`. Each call logs its start, duration, and
  outcome on `onya.model` (no prompt text, no secrets). Search the
  function logs for `"event": "model_call"`.
- Rate limits and the token budget live in Upstash Redis (atomic
  Lua claims). Without Redis configured or reachable, `POST`
  fails closed with the paused message.
- In production the bundle is read-only: runtime writes (fetch
  cache, select cache, traces, fresh extractions) go to `/tmp/onya`,
  and reads check the bundled file first
  ([src/runtime_paths.py](src/runtime_paths.py)).

## 1. Create the API secrets (Vercel dashboard, onya-api project)

Create the `onya-api` project first: import the GitHub repo, root
directory = repo root (leave empty), framework = Other. Add these to
the Production environment only (server-only, never `NEXT_PUBLIC_`):

- `META_API_KEY`
- `ONYA_DEMO_TOKEN` - generate a NEW production token, different
  from any local token. Run this, copy the output straight into the
  secret field, and do not print it anywhere else:

  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

  The same new token goes into the site project in step 5.

- `SEC_USER_AGENT` - the SEC's fair-access rule requires a
  User-Agent naming a contact email (requests without one get 403).
  Value form: `OnyaDemo/1.0 you@example.com`. The API refuses to
  start in production when it is missing or has no `@`.
- `META_BASE_URL` = `https://api.meta.ai/v1`
- `BASETEN_API_KEY` and `BASETEN_BASE_URL` - the Muse Spark Open
  model endpoint used only by private mode (`POST /private/compare`).
  Both are Sensitive, Production-only; when either is missing the
  endpoint returns 503 and the site says private mode is unavailable.
- `ONYA_ENV` = `production`
- `ONYA_FRONTEND_ORIGIN` = the site URL from step 5
  (for example `https://onya.vercel.app`)
- `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` from
  step 2.

## 2. Create the Redis database (Upstash website)

Sign up directly at Upstash (the free tier needs no card) and create
a Regional database in the region closest to the site. Do NOT use a
pay-as-you-go database: it cannot scale to zero and bills hourly.
Copy the REST URL and REST token into the two `UPSTASH_*` env vars
in step 1, then deploy `onya-api` from the dashboard and note its
URL (`https://<api-project>.vercel.app`).

## 3. Import the site (Vercel dashboard, site project)

Import the same repo as a second project. Set the root directory to
`web/`. Framework preset: Next.js. Add to the Production
environment only:

- `ONYA_API_BASE` = the `onya-api` URL from step 2
- `ONYA_DEMO_TOKEN` = the NEW production token from step 1

Public:

- `NEXT_PUBLIC_REPO_URL` = the public GitHub repo URL (optional; the
  footer GitHub link hides itself when unset)

Do NOT set `NEXT_PUBLIC_API_BASE` or `BASETEN_API_KEY`; the prebuild
check fails on purpose if either is present. Deploy from the
dashboard.

## 4. Smoke test (your WSL terminal)

```bash
scripts/smoke_prod.sh https://<api-project>.vercel.app https://<site-url>
```

All lines should say OK. Then open the site, run the agent once on
Sleep Number, and follow a memo figure link.

To load test (spends real tokens and counts against the rate limits):

```bash
scripts/load_test.py https://<site-url>
```

## Roll back

- Either project: in the dashboard, open Deployments and promote
  the previous production deployment. API and site version
  independently; a site-only change never needs an API redeploy.
- The site treats 45 s of silence on a run as a lost connection and
  relies on the API's heartbeats. If you roll the API back to a version
  from before heartbeats, roll the site back with it.

## Kill switch and budget

- Pause the live agent: set `ONYA_AGENT_ENABLED` to 0 in the
  `onya-api` Production env vars and redeploy. `POST /agent/run`
  returns 503 and the site shows "The live agent is paused." with a
  link to the recorded run. Set it back to 1 to resume.
- Daily token budget: `ONYA_DAILY_TOKEN_BUDGET` in the same place
  (default 1500000). When the day's recorded tokens reach it,
  `POST /agent/run` returns 429 and the site offers the recorded run.

## Appendix: other backend targets

Vercel above is the default. Two alternatives stay in the repo but
are no longer the documented path:

- Baseten Truss: [deploy/baseten/config.yaml](deploy/baseten/config.yaml),
  `scripts/stage_baseten.py`, and the `/secrets` file reader in
  [src/secret_files.py](src/secret_files.py) (still used: values come
  from the environment when no secret files exist).
- Hugging Face Docker Space: [deploy/hf/Dockerfile](deploy/hf/Dockerfile)
  plus `scripts/deploy_hf.py <space-id>` (needs `huggingface_hub`
  from requirements-deploy.txt). Free Spaces sleep without traffic;
  the site shows a waking-up notice with a Retry button meanwhile.
- Modal: `modal_app.py` with a Modal secret named `onya-prod`.

On any alternative target, set the site's `ONYA_API_BASE` to that
target's base URL instead of the `onya-api` URL.
