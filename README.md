# Onya

Onya is a covenant monitoring agent for private credit lenders.

Live demo: https://onya-g8f4.vercel.app (public SEC data, no sign-up).

## The Sleep Number case

Sleep Number (SNBR) is the fully worked case. For the Apr 4, 2026 test
(as of May 19, 2026) Onya computes net leverage 5.06x with $44M of
projected savings and 6.58x without, against a 4.75x limit: breach in
both scenarios. The governing document is the Apr 28, 2026 forbearance
agreement and thirteenth amendment. Sources: `data/results/snbr_2026-04-04.json`,
`data/results/snbr_projection_2026-04-04.json`. See [EVIDENCE.md](EVIDENCE.md).

## Features

- Agent covenant check: streamed run over real EDGAR filings, deterministic
  Python math, memo with linked figures. Page: `/app/agent`.
- Borrower information request: the agent drafts it after the memo when there
  is a breach or high risk; the case page has a "Draft information request"
  button that streams only this tool. The letter is a draft marked
  "Draft. Review before sending." Nothing is sent anywhere. The reply-by line
  is left as `[lender to fill]`. Code: `src/info_request.py`.
- Watch list: per-browser localStorage list with a toggle on watchlist rows
  and the case header, a Watching count in the sidebar, and a Next test
  column (date, limit, projected ratio with risk). No account, no backend
  identity, no alerts sent. Code: `web/lib/watch.ts`.
- Filed since this check: 10-K, 10-Q and 8-K filings after the as-of date,
  read from the cached submissions file only, with SEC.gov links.
  Endpoint: `GET /company/{ticker}/filings-since?date=YYYY-MM-DD`.
  Missing cache returns `cached: false` with a note.

## Run it locally

API: `.venv/bin/python -m unittest` from the repo root.
Site: `npm run dev` in `web/` (needs `ONYA_API_BASE` plus the demo token).

## Tests

Python suite, JS tests (`npm run test:what-if` in `web/`), Playwright
(`npx playwright test` in `web/`), `next build`, `npm run lint`.

Onya supports review by credit professionals. It is not financial, legal
or investment advice.
