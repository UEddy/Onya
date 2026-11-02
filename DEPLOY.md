# Onya deploy runbook

Backend on a Hugging Face Docker Space (free CPU), frontend on Vercel.
Do the steps in order. Nothing here contains a secret value; never
paste a secret into chat, git, or a file in this repo.

## 1. Create the Space (Hugging Face website)

Create a free Hugging Face account, then create a new Space:

- SDK: Docker
- Hardware: CPU basic (free)
- Visibility: Public

Note the Space id (for example `UEddy/onya-api`). Its URL will be
`https://<owner>-<space-name>.hf.space`, for example
`https://ueddy-onya-api.hf.space`.

## 2. Log in from WSL (your WSL terminal)

Make a fine-grained token first: on the Hugging Face website, open
Settings, Access Tokens, Create new token, type Fine-grained, and give
it write access to only this one Space. Then:

```bash
cd /home/eddy/dev/onya
.venv/bin/pip install -r requirements-deploy.txt
.venv/bin/huggingface-cli login
```

Paste the token into the CLI prompt. The CLI stores it outside the
repo (in your Hugging Face config home), never in this repo.

## 3. Add the Space secrets (Hugging Face website)

In the Space, open Settings, Variables and secrets, and add these
secret keys (names only here; values are yours):

- `META_API_KEY`
- `META_BASE_URL`
- `SEC_USER_AGENT`
- `ONYA_DEMO_TOKEN`
- `ONYA_FRONTEND_ORIGIN` - set it to `https://placeholder.invalid`
  for now (step 7 replaces it)
- `ONYA_ENV` - value: production

Optional: `ONYA_AGENT_ENABLED`, `ONYA_DAILY_TOKEN_BUDGET`.

Generate a NEW production `ONYA_DEMO_TOKEN`, different from any local
token. Run this, copy the output straight into the Space settings
field, and do not print it anywhere else:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

The same new token goes into Vercel in step 6.

## 4. Upload and watch the build (your WSL terminal, then the Space page)

```bash
.venv/bin/python scripts/deploy_hf.py UEddy/onya-api
```

Use your Space id. The script prints the staged file list and total
size and asks before uploading (add `--yes` to skip the question).
Then open the Space page and watch the build logs until it is running.
Check:

```bash
curl -s https://<owner>-<space-name>.hf.space/health
```

It should answer `{"status":"ok"}`. Free Spaces sleep without
traffic; the first request after a sleep can take up to a minute, and
the site shows a waking-up notice with a Retry button meanwhile.

## 5. Import the site (Vercel dashboard)

Import the GitHub repo in Vercel. In the GitHub app settings, give
Vercel access to the Onya repo only. Set the root directory to `web/`.
Framework preset: Next.js.

## 6. Set the Vercel env vars (Vercel dashboard, Production only)

Add these to the Production environment only.

Server-only (never prefix these with NEXT_PUBLIC):

- `ONYA_API_BASE` = the Space URL from step 4
- `ONYA_DEMO_TOKEN` = the NEW production token from step 3

Public:

- `NEXT_PUBLIC_API_BASE` = the Space URL from step 4
- `NEXT_PUBLIC_REPO_URL` = the public GitHub repo URL (optional; the
  footer GitHub link hides itself when unset)

The build fails on purpose if any `NEXT_PUBLIC_` name contains TOKEN,
KEY or SECRET (scripts/check-env.mjs). Deploy from the dashboard.

## 7. Point production CORS at the site (Hugging Face website)

In the Space Settings, Variables and secrets, set
`ONYA_FRONTEND_ORIGIN` to the Vercel URL (for example
https://onya.vercel.app). The Space restarts itself with the new
value.

## 8. Smoke test (your WSL terminal)

```bash
scripts/smoke_prod.sh https://<owner>-<space-name>.hf.space https://<site-url>
```

All lines should say OK. Then open the site, run the agent once on
Sleep Number, and follow a memo figure link.

## Roll back

- Space: on the Space page, open Settings and use the factory rebuild
  from an earlier commit in the Space's Files history, or re-run
  `scripts/deploy_hf.py` from a checkout of the last good commit.
- Vercel: in the dashboard, open Deployments and promote the previous
  production deployment.

## Kill switch and budget

- Pause the live agent: in the Space secrets set `ONYA_AGENT_ENABLED`
  to 0. The Space restarts itself; `POST /agent/run` returns 503 and
  the site shows "The live agent is paused. See a saved run." Set it
  back to 1 to resume.
- Daily token budget: `ONYA_DAILY_TOKEN_BUDGET` in the same secrets
  (default 1500000). When the day's recorded tokens reach it,
  `POST /agent/run` returns 429 and the site shows the saved-run
  fallback.

## Appendix: Modal alternative

modal_app.py stays in the repo. To use Modal instead of the Space:
install the Modal CLI into .venv, run `modal setup`, create one Modal
secret named `onya-prod` with the same key names as step 3 (including
`ONYA_ENV=production` and the real `ONYA_FRONTEND_ORIGIN`), then
`.venv/bin/modal deploy modal_app.py`, and point the Vercel env vars
at the Modal web endpoint URL instead of the Space URL. The run-state
choice (one pinned container) and all production guards are identical
on both targets.
