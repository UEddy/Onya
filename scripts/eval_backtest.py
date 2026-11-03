#!/usr/bin/env python3
"""Recompute the back-test totals from committed data. No network, no model.

Rescores each disclosed covenant against the answer key, and each contract
limit from the saved extraction against the company's disclosure. Prints the
totals and exits non-zero if they differ from the ones the site and README
state.
"""

import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SEC_USER_AGENT", "onya-eval eval@example.invalid")
os.chdir(ROOT)

EXPECTED = {"disclosed": (23, 23), "limits": (19, 21)}


def _no_network(*args, **kwargs):
    raise OSError("eval_backtest uses committed data only")


def _strip_fences(text):
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def recompute(backtest_dir=None):
    """Totals scored from the committed extractions and answer key."""
    socket.getaddrinfo = _no_network
    socket.create_connection = _no_network
    import backtest_terms
    import score_disclosed

    backtest = Path(backtest_dir or ROOT / "data" / "backtest")
    rows = []
    for ticker, expected in score_disclosed.load_key().items():
        extraction = score_disclosed.load_disclosed(ticker)
        rows.extend(score_disclosed.score_company(
            ticker, expected, extraction)[0])

    limits = []
    cases = json.loads((backtest / "companies.json").read_text())
    for case in cases:
        ticker = case["ticker"]
        terms_path = backtest / f"terms_{ticker}.json"
        raw_path = backtest / f"terms_{ticker}_raw.txt"
        if ticker == "SNBR" or not terms_path.exists():
            continue
        record = json.loads(terms_path.read_text())
        if record.get("status") != backtest_terms.STATUS_OK \
                or not raw_path.exists():
            continue
        saved = record.get("covenants") or []
        # Quote diagnostics, when present, follow the model's JSON.
        raw = raw_path.read_text().split(backtest_terms.DIAGNOSTICS_MARKER)[0]
        agreement = json.loads(_strip_fences(raw))
        disclosed = score_disclosed.load_disclosed(ticker) or {}
        scored, _ = backtest_terms.score_terms(
            ticker, record["period_end"],
            agreement.get("financial_covenants") or [],
            disclosed.get("covenants") or [],
            record.get("agreement_url"),
            [row.get("quote_verified") for row in saved])
        limits.extend(scored)
    return {
        "disclosed": (sum(1 for r in rows if r["matched"]), len(rows)),
        "limits": (sum(1 for r in limits if r["match"]), len(limits)),
        "amended": sum(1 for r in limits
                       if r["status"] == backtest_terms.ROW_AMENDED),
        "mismatched": sum(1 for r in limits
                          if r["status"] == backtest_terms.ROW_MISMATCH),
    }


def main(expected=None):
    expected = expected or EXPECTED
    totals = recompute()
    disclosed, limits = totals["disclosed"], totals["limits"]
    print(f"Disclosed figures: {disclosed[0]} of {disclosed[1]} matched")
    print(f"Contract limits: {limits[0]} of {limits[1]} matched "
          f"({totals['amended']} changed by later amendments, flagged; "
          f"{totals['mismatched']} mismatched)")
    if disclosed != expected["disclosed"] or limits != expected["limits"]:
        print(f"FAILED: expected {expected['disclosed'][0]} of "
              f"{expected['disclosed'][1]} disclosed figures and "
              f"{expected['limits'][0]} of {expected['limits'][1]} contract "
              "limits.", file=sys.stderr)
        return 1
    print("OK: totals match the README and the site.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
