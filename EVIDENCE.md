# EVIDENCE.md

Each row ties a claim in the README or on the site to its exact value,
its source, and the command or test that reproduces it.

## Sleep Number reproductions

| Claim | Value | Source | Reproduce |
|---|---|---|---|
| Q3 2025 net leverage | 4.97x vs 5.25x limit, pass | `data/results/snbr_2025-09-27.json` | `.venv/bin/python -m unittest tests.test_api` |
| Q3 2025 company disclosed leverage | 5.0x vs 5.25x limit, in compliance, quote verified | `data/backtest/disclosed_SNBR.json` | `PYTHONPATH=src .venv/bin/python -c "import score_disclosed; score_disclosed.main()"` |
| Q3 2025 EBITDA reconciliation | Company $84,597,000 vs Onya $84,597,000, difference $0 | `data/results/snbr_2025-09-27.json` (reconciliation) | `.venv/bin/python -m unittest tests.test_api` |
| Jan 3, 2026 net leverage with $50M savings | 4.25x vs 4.50x limit, pass | `data/results/snbr_2026-01-03.json`; disclosed $50M in `data/results/snbr_projection_2026-01-03.json` | `.venv/bin/python -m unittest tests.test_api` |
| Jan 3, 2026 net leverage without savings | 5.47x vs 4.50x limit, fail | `data/results/snbr_2026-01-03.json` (sensitivity_without_proforma) | `.venv/bin/python -m unittest tests.test_api` |
| Apr 4, 2026 net leverage with $44M savings | 5.06x vs 4.75x limit, fail | `data/results/snbr_2026-04-04.json` (proforma_scenarios) | `.venv/bin/python -m unittest tests.test_api` |
| Apr 4, 2026 net leverage without savings | 6.58x vs 4.75x limit, fail | `data/results/snbr_2026-04-04.json` (proforma_scenarios) | `.venv/bin/python -m unittest tests.test_api` |
| Apr 4, 2026 interest coverage | 0.84x vs 2.10x minimum, fail | `data/results/snbr_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_api` |
| Governing document as of May 19, 2026 | Forbearance agreement and thirteenth amendment, filed Apr 28, 2026 | `data/cache/select_0000827187_2026-05-19.json` | `.venv/bin/python -m unittest tests.test_asof_regression` |
| Forbearance filing | 8-K EX-10.1, Apr 28, 2026 | https://www.sec.gov/Archives/edgar/data/827187/000082718726000035/ex101thirteenthamendmentto.htm | fetch with SEC User-Agent, returns 200 |
| Chapter 11 filing | 8-K, filed Jun 12, 2026 | https://www.sec.gov/Archives/edgar/data/827187/000095010326008891/dp248362_8k.htm | fetch with SEC User-Agent, returns 200 |

## Request, cure, and next test

| Claim | Value | Source | Reproduce |
|---|---|---|---|
| (a)(iv) add-back claimed | $19,841,000 | `src/info_request.py`, `tests/test_info_request.py` | `.venv/bin/python -m unittest tests.test_info_request` (8 passed) |
| (a)(viii) add-back claimed | $23,891,000 | `src/info_request.py`, `tests/test_info_request.py` | `.venv/bin/python -m unittest tests.test_info_request` |
| Shared (a)(iv)/(a)(viii) cap | $25,000,000 for periods ending Sep 27, 2025 through Oct 3, 2026 | `data/extracted/snbr_covenants.reviewed.json` (cap group cap_ebitda_aiv_aviii, with agreement quote) | `.venv/bin/python -m unittest tests.test_info_request` |
| Add-backs disallowed over the cap | $18,732,000 | $19,841,000 + $23,891,000 - $25,000,000; `disallowed` in `data/results/snbr_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_info_request` |
| (a)(ix) projected savings cap | $44,000,000 | `data/results/snbr_projection_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_info_request` |
| Cure: debt reduction to pass Apr 4 | $267,190,000 | `data/results/snbr_2026-04-04.json` (cure.figures.debt_reduction_needed) | `.venv/bin/python -m unittest tests.test_cure` |
| Cure: EBITDA increase to pass Apr 4 | $56,250,526.32 | `data/results/snbr_2026-04-04.json` (cure.figures.ebitda_increase_needed) | `.venv/bin/python -m unittest tests.test_cure` |
| Next test | Jul 4, 2026, limit 4.80x, projected 6.58x, high risk | `data/results/snbr_projection_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_api` |
| Filings after May 19, 2026 | 8 8-K rows, May 27 to Aug 3, 2026, with SEC links, cache only | `data/raw/submissions_CIK0000827187.json` | `.venv/bin/python -m unittest tests.test_api.FilingsSince` |
| Memo verifier on Apr 4 figures | 9 figures checked, 0 unverified | `src/agent.py` (`verify_memo_numbers`) | `.venv/bin/python -m unittest tests.test_agent.MemoValidators` (8 passed) |

## Back-test tables

Disclosed figures per company, from `data/backtest/disclosed_<TICKER>.json`
scored against `data/backtest/answer_key.json` with
`PYTHONPATH=src .venv/bin/python -c "import score_disclosed;
score_disclosed.main()"`:

| Company | Matched | Quote verified |
|---|---|---|
| AIN | 2/2 | 2 |
| AMCX | 2/2 | 1 (interest coverage matched but unverified) |
| CRS | 2/2 | 2 |
| GPK | 2/2 | 2 |
| HAIN | 3/3 | 3 |
| NUVR | 2/2 | 2 |
| OPTX | 2/2 | 2 |
| ORLY | 2/2 | 2 |
| QUAD | 2/2 | 2 |
| SNBR | 1/1 | 1 |
| STGW | 1/1 | 1 |
| TRS | 2/2 | 2 |
| Total | 23/23 | 22 |

Contract thresholds per company, from `data/backtest/terms_<TICKER>.json`
(served by `GET /backtest`, assembled in `src/api.py get_backtest`):

| Company | Result |
|---|---|
| AIN | 2 matched |
| AMCX | base agreement not found (searched 2015-01-01 to 2025-11-14) |
| CRS | 2 matched |
| GPK | 1 amended after agreement (leverage schedule ends Dec 31, 2025; company discloses 5.0x for Jun 30, 2026); 1 mismatch (interest expense ratio) |
| HAIN | 1 matched; 2 amended after agreement |
| NUVR | 2 matched |
| OPTX | base agreement not found (searched 2015-01-01 to 2026-05-15) |
| ORLY | 2 matched |
| QUAD | base agreement not found (searched 2015-01-01 to 2026-08-14) |
| STGW | 1 matched |
| TRS | 2 matched |
| Total | 12 matched, 3 amended after agreement, 1 mismatch |

## Suite counts

| Suite | Count | Command |
|---|---|---|
| Python | 538 passed | `.venv/bin/python -m unittest` over named `tests.test_*` modules |
| JS | 17 passed | `npm run test:what-if` in `web/` |
| Playwright | 11 passed | `npx playwright test` in `web/` |
| Watch storage | passed | `web/lib/watch.test.ts` via `test:what-if` |
| Watch plus request flow | 3 passed | `web/e2e/watch-request.spec.ts` |
