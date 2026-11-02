# Onya deploy runbook

Backend on Modal, frontend on Vercel. Do the steps in order. Nothing in
this runbook contains a secret value; never paste a secret into chat,
git, or a file in this repo.

## 1. Install the Modal CLI (your WSL terminal)

```bash
cd /home/eddy/dev/onya
.venv/bin/pip install modal
```

## 2. Authenticate Modal (your WSL terminal, opens the browser)

```bash
.venv/bin/modal setup
```

## 3. Create the production secret (Modal dashboard)

In the Modal dashboard, create one secret named `onya-prod` with these
keys (names only here; values are yours):

- `META_API_KEY`
- `META_BASE_URL`
- `SEC_USER_AGENT`
- `ONYA_DEMO_TOKEN`
- `ONYA_FRONTEND_ORIGIN` (set in step 7, after the Vercel deploy)
- `ONYA_ENV` (value: production)

Generate a NEW production `ONYA_DEMO_TOKEN`, different from any local
token, and paste it straight into the dashboard. Do not print it
anywhere else:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output directly into the Modal dashboard field, then clear
your terminal scrollback if it bothers you. The same new token goes
into Vercel in step 6.

## 4. Deploy the backend (your WSL terminal)

```bash
cd /home/eddy/dev/onya
.venv/bin/modal deploy modal_app.py
```

Note the web endpoint URL Modal prints. That is the API URL.

Cold start: after at least 10 idle minutes, time
`curl -s https://<api-url>/health` once; the first request pays the
cold start. Repeat when warm for comparison.

## 5. Import the site (Vercel dashboard)

Import the GitHub repo in Vercel and set the root directory to `web/`.
Framework preset: Next.js.

## 6. Set the Vercel env vars (Vercel dashboard)

Server-only (never prefix these with NEXT_PUBLIC):

- `ONYA_API_BASE` = the Modal API URL from step 4
- `ONYA_DEMO_TOKEN` = the NEW production token from step 3

Public:

- `NEXT_PUBLIC_API_BASE` = the Modal API URL from step 4
- `NEXT_PUBLIC_REPO_URL` = the public GitHub repo URL (optional; the
  footer GitHub link hides itself when unset)

The build fails on purpose if any `NEXT_PUBLIC_` name contains TOKEN,
KEY or SECRET (scripts/check-env.mjs).

## 7. Point production CORS at the site (Modal dashboard)

Set `ONYA_FRONTEND_ORIGIN` in the `onya-prod` secret to the Vercel URL
(for example https://onya.vercel.app), then redeploy Modal:

```bash
.venv/bin/modal deploy modal_app.py
```

## 8. Smoke test (your WSL terminal)

```bash
scripts/smoke_prod.sh https://<api-url> https://<site-url>
```

All lines should say OK. Then open the site, run the agent once on
Sleep Number, and follow a memo figure link.

## Roll back

- Vercel: in the dashboard, open Deployments and promote the previous
  production deployment. No code change is needed.
- Modal: redeploy the previous code with
  `.venv/bin/modal deploy modal_app.py` from a checkout of the last
  good commit, or stop the app in the Modal dashboard with Apps, onya,
  Stop. The previous Vercel deployment keeps working against a stopped
  API only for public pages that do not need the API.

## Kill switch and budget

- Pause the live agent: in the `onya-prod` secret set
  `ONYA_AGENT_ENABLED` to 0 and redeploy Modal. `POST /agent/run`
  returns 503 and the site shows "The live agent is paused. See a saved
  run." Set it back to 1 (or remove it) and redeploy to resume.
- Daily token budget: `ONYA_DAILY_TOKEN_BUDGET` in the same secret
  (default 1500000). When the day's recorded tokens reach it,
  `POST /agent/run` returns 429 and the site shows the saved-run
  fallback. Raise it and redeploy to lift the cap early.

## Notes

- Run state lives in the single pinned Modal container
  (max_containers=1): runs, traces, rate limits (5 per hour per
  visitor, 30 per day overall) and the token ledger reset if the
  container restarts. Losing an in-flight run on a restart is accepted
  for the demo; modal.Dict plus a Volume is the documented upgrade
  path in modal_app.py.
- The demo token never reaches the browser: it is a server-only Vercel
  env var used by the Next.js route handlers, and
  `npm run test:bundle` (after a build) proves its value is absent
  from .next/static.
