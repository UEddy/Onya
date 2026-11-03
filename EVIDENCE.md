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
| Governing document as of May 19, 2026 | Forbearance agreement and thirteenth amendment, filed Apr 28, 2026 | `tests/fixtures/sec/select_0000827187_2026-05-19.json` | `.venv/bin/python -m unittest tests.test_asof_regression` |
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
| Memo verifier on sample run `7c2a49625f4e` | 42 of 42 memo figures traced to tool output | `data/samples/snbr_memo.json` (`figures_checked`); corpus `data/results/snbr_2026-04-04.json`, `data/results/snbr_projection_2026-04-04.json`, `data/extracted/snbr_covenants.reviewed.json`, `tests/fixtures/sec/select_0000827187_2026-05-19.json` | `.venv/bin/python -m unittest tests.test_agent.MemoValidators.test_sample_memo_verifies_42_of_42` |

## Why Muse Spark

`Local check` and `SEC check` are the two commands below the table. Quotes
from Hugging Face were read from the linked pages.

| Claim | Value | Source | Reproduce |
|---|---|---|---|
| Sleep Number prompt size | 496,322 exhibit characters; 500,622 with instructions; about 106,000 tokens (estimate, 500,622 / 4.7374) | `data/raw/snbr_13th_amendment.htm`; `src/extract.py` (`INSTRUCTIONS`) | Local check |
| Logged back-test token counts | QUAD 148,372; AMCX 147,634 | `model_usage` in `data/backtest/terms_QUAD.json` and `terms_AMCX.json` | Local check |
| Characters per token | 4.74, or 4.7374 before rounding (1,402,310 characters / 296,006 tokens, QUAD and AMCX) | Same `model_usage` fields; characters from the next row | SEC check |
| Back-test prompt characters | GPK 809,926; QUAD 705,998; AMCX 696,312; TRS 662,824; HAIN 607,769; STGW 594,892; CRS 556,849; NUVR 542,693; AIN 509,006; ORLY 430,673 | Filing at `agreement_url` in `data/backtest/terms_<TICKER>.json`; `build_content` in `src/backtest_terms.py` | SEC check |
| Estimated back-test tokens | Prompt characters / 4.7374 (the ratio before rounding), to the nearest 1,000 | README table | Arithmetic on the rows above |
| OPTX not read | Agreement filed as scanned images | `status` in `data/backtest/terms_OPTX.json` | Local check |
| Nearest cap | Covers only (a)(ix); starts 666 characters after (a)(viii) | Cap group `cap_ebitda_aix` in `data/extracted/snbr_covenants.reviewed.json`; `data/raw/snbr_13th_amendment.htm` | Local check |
| Shared cap | $25,000,000 for the Apr 4, 2026 test; governs (a)(iv) and (a)(viii) together; 1,591 characters after (a)(viii) | Cap group `cap_ebitda_aiv_aviii` in `data/extracted/snbr_covenants.reviewed.json`; `data/raw/snbr_13th_amendment.htm` | Local check |
| Each clause against the cap alone | $0 disallowed; 5.83x; 4.60x with $44M, pass against 4.75x. Arithmetic, not a recorded model run | $962,096,000 / $165,028,000 and / $209,028,000, from `data/results/snbr_2026-04-04.json` | Local check |
| One shared cap | $18,732,000 disallowed; 6.58x; 5.06x with $44M, fail against 4.75x | `data/results/snbr_2026-04-04.json` | `.venv/bin/python -m unittest tests.test_api` |
| Reviewed quotes | 52 quotes, 50 distinct, all 52 found after `normalize` | `data/extracted/snbr_covenants.reviewed.json`; `data/raw/snbr_13th_amendment.htm` | Local check |
| Model's as-of date in sample run `7c2a49625f4e` | May 19, 2026 on all 7 tool calls; test date plus the 45-day window | `data/samples/snbr_memo.json` (`steps`); system prompt in `src/agent.py` | Local check |
| Agreement chosen in that run | Forbearance agreement and thirteenth amendment, filed Apr 28, 2026; document type forbearance | `data/samples/snbr_memo.json` (`find_agreements` step); `tests/fixtures/sec/select_0000827187_2026-05-19.json` | `.venv/bin/python -m unittest tests.test_asof_regression` |
| Later amendment left out | Fourteenth amendment, filed Jun 16, 2026, excluded and flagged in a memo; 4 tests | https://www.sec.gov/Archives/edgar/data/827187/000095010326009081/dp248436_ex1001.htm; `tests/test_asof_regression.py` | `.venv/bin/python -m unittest tests.test_asof_regression.DiscoveryCutoff tests.test_asof_regression.VerifierRejectsForeignLabels` |
| License terms | "to deal in the Software without restriction", "Built with Muse Spark Open", "internal use, research, or any commercial activity that is not Model as a Service" | https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B/blob/main/LICENSE.md | Read the linked page |
| Weights for download | "on your own system" | https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B | Read the linked page |
| Where Onya has run the model | Baseten only; no self-hosted endpoint tested | `make_baseten_client` in `src/private_compare.py`, `BASETEN_BASE_URL` | Code reading |

Local check (no network, uses committed files):

```bash
PYTHONPATH=src SEC_USER_AGENT=local .venv/bin/python - <<'EOF'
import json
from pathlib import Path
import extract
from textify import html_to_text
doc = html_to_text(Path("data/raw/snbr_13th_amendment.htm").read_bytes())
print("exhibit", len(doc),
      "prompt", len(doc + "\n\n---\n\n" + extract.INSTRUCTIONS))
viii = doc.find("(viii) reasonable cash")
print("(a)(viii) to (a)(ix) cap",
      doc.find("under this clause (a)(ix)") - viii)
print("(a)(viii) to shared cap",
      doc.find("under the foregoing clauses (a)(iv) and (a)(viii)") - viii)
reviewed = json.loads(
    Path("data/extracted/snbr_covenants.reviewed.json").read_text())
for group in reviewed["cap_groups"]:
    print(group["id"], group["applies_to_clauses"],
          [s["amount_usd"] for s in group["schedule"]
           if s["period_end"] == "2026-04-04"])
quotes = []
extract.collect_quotes(reviewed, quotes)
source = extract.normalize(doc)
print("quotes", len(quotes), "distinct", len(set(quotes)),
      "found", sum(extract.normalize(q) in source for q in quotes))
result = json.loads(Path("data/results/snbr_2026-04-04.json").read_text())
debt, ebitdar = result["numerator"], result["ebitdar"]
alone = ebitdar + result["disallowed"]
print("each clause alone", round(debt / alone, 2),
      round(debt / (alone + 44_000_000), 2))
for ticker in ("QUAD", "AMCX", "OPTX"):
    terms = json.loads(
        Path(f"data/backtest/terms_{ticker}.json").read_text())
    print(ticker, terms["status"], terms.get("model_usage"))
memo = json.loads(Path("data/samples/snbr_memo.json").read_text())
calls = [s for s in memo["steps"] if s["type"] == "tool_call"]
print("tool calls", len(calls),
      "as_of", {s["arguments"].get("as_of") for s in calls})
EOF
```

SEC check (fetches each agreement, set `SEC_USER_AGENT` to your contact):

```bash
PYTHONPATH=src .venv/bin/python - <<'EOF'
import json
from pathlib import Path
import backtest_terms as terms
counts = {}
for path in sorted(Path("data/backtest").glob("terms_*.json")):
    record = json.loads(path.read_text())
    if record["ticker"] == "OPTX" or not record.get("agreement_url"):
        continue
    doc, _ = terms.fetch_agreement(
        {"url": record["agreement_url"]}, record["ticker"])
    counts[record["ticker"]] = len(terms.build_content(doc))
    print(record["ticker"], counts[record["ticker"]])
tokens = 148372 + 147634
print("chars per token",
      round((counts["QUAD"] + counts["AMCX"]) / tokens, 4))
EOF
```

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
| AMCX | 2 matched; agreement found by incorporated reference (Amendment No. 3, conformed copy, Apr 10, 2024 8-K). Its "Cash Flow Ratio" (Section 7.27, 5.75x through Mar 31, 2026) pairs by direction with the disclosed total net leverage ratio |
| CRS | 2 matched |
| GPK | 2 matched; Section 8.1 schedule states 5.00x for Mar 31 through Dec 31, 2026, and 3.00x interest expense ratio |
| HAIN | 1 matched; 2 amended after agreement |
| NUVR | 2 matched |
| OPTX | not read: EX-10.12 of the Nov 14, 2023 8-K holds 56 scanned images and no text |
| ORLY | 2 matched |
| QUAD | 3 matched; agreement found by incorporated reference (Aug 20, 2025 agreement, EX-4.7 of the Feb 18, 2026 10-K). The disclosed total net leverage ratio has no separate covenant in the agreement |
| STGW | 1 matched |
| TRS | 2 matched |
| Total | 19 matched, 2 amended after agreement, 0 mismatched, 21 quotes verified |

Rescoring saved extractions costs no tokens:
`PYTHONPATH=src .venv/bin/python src/backtest_terms.py --rescore`. The
AMCX and QUAD extractions used 324,787 Baseten tokens in 2 calls
(`model_usage` in `data/backtest/terms_AMCX.json` and `terms_QUAD.json`).

Back-test totals before and after the extras pass:

| Measure | Before | After |
|---|---|---|
| Disclosed | 23 of 23 matched, 22 verified | unchanged |
| Terms rows | 16 | 21 |
| Terms matched | 12 | 19 |
| Terms amended after agreement | 3 | 2 |
| Terms mismatched | 1 | 0 |
| Companies with no agreement read | 3 (AMCX, QUAD, OPTX) | 1 (OPTX) |
| Recomputed from XBRL, other borrowers | none | 12 ratios: 0 full, 12 partial, 0 mismatched |

Recomputed leverage ratios, from `data/backtest/recompute_<TICKER>.json`
with `PYTHONPATH=src .venv/bin/python src/backtest_recompute.py` (no model
calls). A partial figure uses only the components XBRL could supply:

| Company | Ratio | Recomputed | Disclosed | Difference | Status |
|---|---|---|---|---|---|
| AIN | Leverage Ratio | not computed | 1.71x |  | partial |
| AMCX | Cash Flow Ratio | not computed | 4.33x |  | partial |
| CRS | Consolidated Net Leverage Ratio | 0.60x | 0.59x | +0.01x | partial |
| GPK | Consolidated Total Leverage Ratio | 5.03x | 4.37x | +0.66x | partial |
| HAIN | Consolidated Secured Leverage Ratio | not computed | 4.81x |  | partial |
| HAIN | Consolidated Leverage Ratio | not computed | 4.81x |  | partial |
| NUVR | Maximum Leverage Ratio | 4.45x | 4.99x | -0.54x | partial |
| ORLY | Consolidated Leverage Ratio | not computed | 2.07x |  | partial |
| QUAD | Maximum Total Leverage Ratio | not computed | 2.00x |  | partial |
| QUAD | Maximum Senior Secured Leverage Ratio | not computed | 1.99x |  | partial |
| STGW | Total Leverage Ratio | not computed | 3.16x |  | partial |
| TRS | Total Net Leverage Ratio | 2.80x | 2.29x | +0.51x | partial |
| Total | 12 ratios | 4 with a figure | | | 0 full, 12 partial, 0 mismatched |

## Private check

| Claim | Value | Source | Reproduce |
|---|---|---|---|
| Sample certificate figures | EBITDA $87,230,000 incl. $44,000,000 savings; debt $962,096,000; reported 5.06x as in compliance with forbearance | `data/samples/sample_certificate_snbr.txt` | `GET /private/sample` |
| Real run on the sample | Net leverage cert 5.06 vs Onya 6.58 (diff -1.52); interest coverage cert 1.7 vs Onya 0.84 (diff +0.86); both figures verified; 5,572 tokens | `src/private_compare.py` (`run_compare`) | Baseten run logged in the H report; replay file below pins the extraction |
| Replay extraction | 2 covenants, 5 components, all quotes verified | `data/samples/private_compare_replay.json` | `.venv/bin/python -m unittest tests.test_private_compare.Endpoint.test_replay_stream_returns_result` |
| Gap flags | $18,732,000 disallowed over the cap; $87,230,000 cert EBITDA over $43,230,000 pre-savings needs administrative agent approval | `src/private_compare.py` (`compare_with_onya`) | `.venv/bin/python -m unittest tests.test_private_compare.ComparisonMath` |
| File validation | PDF/text sniffed by content; 2 MB cap; encrypted and malformed PDFs rejected with content-free errors | `src/private_compare.py` | `.venv/bin/python -m unittest tests.test_private_compare.FileValidation` |
| No persistence | Data dir unchanged; upload marker absent from logs; errors carry no content | `src/private_compare.py` (logs sizes only) | `.venv/bin/python -m unittest tests.test_private_compare.NoPersistence` |
| Missing model config | 503 with an unavailable notice | `src/api.py` (`stream_private_compare`) | `.venv/bin/python -m unittest tests.test_private_compare.Endpoint.test_503_without_baseten_key` |
| Sample flow in the browser | Sample loads; table shows 5.06 vs 6.58 with Verified marks | `web/e2e/private.spec.ts` | `npx playwright test e2e/private.spec.ts` in `web/` |

## Suite counts

| Suite | Count | Command |
|---|---|---|
| Python | 625 passed | `.venv/bin/python -m unittest` over named `tests.test_*` modules |
| JS | 21 passed | `npm run test:what-if` in `web/` |
| Playwright | 19 passed | `npx playwright test` in `web/` |
| Watch storage | passed | `web/lib/watch.test.ts` via `test:what-if` |
| Watch plus request flow | 3 passed | `web/e2e/watch-request.spec.ts` |
| Recomputed section, 1366px and 360px | 3 passed | `web/e2e/accuracy-recompute.spec.ts` |
| What-if Set to cure and agent page line | 4 passed | `web/e2e/what-if-cure.spec.ts` |
