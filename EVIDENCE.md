# EVIDENCE.md

Each row ties a claim on the site to its value, its source, and the command
or test that reproduces it.

| Claim | Value | Source | Reproduce |
|---|---|---|---|
| SNBR Apr 4, 2026 net leverage with $44M savings | 5.06x vs 4.75x limit, breach | `data/results/snbr_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_api` |
| SNBR Apr 4, 2026 net leverage without savings | 6.58x vs 4.75x limit, breach | `data/results/snbr_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_api` |
| (a)(iv) add-back claimed | $19,841,000 | `src/info_request.py`, `tests/test_info_request.py` | `.venv/bin/python -m unittest tests.test_info_request` |
| (a)(viii) add-back claimed | $23,891,000 | `src/info_request.py`, `tests/test_info_request.py` | `.venv/bin/python -m unittest tests.test_info_request` |
| Shared (a)(iv)/(a)(viii) cap | $25,000,000 | agreement terms in `src/covenant.py` | `.venv/bin/python -m unittest tests.test_info_request` |
| Add-backs disallowed over the cap | $18,732,000 | $19,841,000 + $23,891,000 - $25,000,000 | `.venv/bin/python -m unittest tests.test_info_request` |
| (a)(ix) projected savings cap | $44,000,000 | `data/results/snbr_projection_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_info_request` |
| SNBR next test date and limit | Jul 4, 2026, 4.80x | `data/results/snbr_projection_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_api` |
| SNBR projected ratio at next test | 6.58x, high risk | `data/results/snbr_projection_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_api` |
| SNBR filings after May 19, 2026 | 8 8-K rows, May 27 to Aug 3, 2026, with SEC links | `data/raw/submissions_CIK0000827187.json` | `.venv/bin/python -m unittest tests.test_api.FilingsSince` |
| Filings endpoint uses no live SEC call | `cached: true`, offline only | `src/edgar.py` (`filings_since`) | `.venv/bin/python -m unittest tests.test_api.FilingsSince.test_no_live_call_in_request_path` |
| Request builder figures trace to tool output | 8 passed | `tests/test_info_request.py` | `.venv/bin/python -m unittest tests.test_info_request` |
| Watch storage round-trips per browser | passed | `web/lib/watch.test.ts` | `npm run test:what-if` in `web/` |
| Watch plus request flow in the browser | 3 passed | `web/e2e/watch-request.spec.ts` | `npx playwright test e2e/watch-request.spec.ts` in `web/` |

Style rule for these files: no U+2014 or U+2013 code points. The web
`npm run lint` script checks dashes; Python sources and these docs are
checked with a code-point grep before commit.
