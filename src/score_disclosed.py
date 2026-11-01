"""Score disclosed-covenant extractions against the hand-entered answer key.

Compares each data/backtest/disclosed_<TICKER>.json with
data/backtest/answer_key.json and prints one row per key covenant:
company, covenant, extracted vs key for actual and threshold with
match yes/no, plus matched (value equals key), verified (quote
passed), and matched_and_verified columns with totals for all three.
An unverified match must not count as a verified result. The answer
key is used ONLY here, never as extractor input.

Usage:
    python src/score_disclosed.py [TICKER ...]
with no tickers scoring every company in the answer key.
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_DIR = PROJECT_ROOT / "data" / "backtest"
ANSWER_KEY_PATH = BACKTEST_DIR / "answer_key.json"

TOLERANCE = 0.01

STOPWORDS = frozenset({"ratio", "ratios", "test", "covenant", "the", "of"})


def load_key(path=ANSWER_KEY_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_disclosed(ticker, backtest_dir=BACKTEST_DIR):
    path = Path(backtest_dir) / f"disclosed_{ticker}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def name_tokens(name):
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {w for w in words if w not in STOPWORDS}


def match_covenants(key_covs, ext_covs):
    """Pair each key covenant with the best same-direction extraction.

    Greedy by key order: the unmatched extracted covenant sharing the
    most name tokens wins; ties break by document order. Returns a list
    of (key_cov, ext_cov_or_None) plus a list of unmatched extras.
    """
    remaining = list(ext_covs or [])
    pairs = []
    for key_cov in key_covs or []:
        key_toks = name_tokens(key_cov.get("name"))
        key_dir = key_cov.get("direction")
        best_idx = None
        best_score = 0
        for i, ext in enumerate(remaining):
            if ext.get("direction") != key_dir:
                continue
            score = len(key_toks & name_tokens(ext.get("name")))
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx is None:
            pairs.append((key_cov, None))
        else:
            pairs.append((key_cov, remaining.pop(best_idx)))
    return pairs, remaining


def numbers_match(ext_value, key_value, tol=TOLERANCE):
    """Null matches null only; numbers match within tolerance."""
    if ext_value is None or key_value is None:
        return ext_value is None and key_value is None
    if isinstance(ext_value, bool) or isinstance(key_value, bool):
        return False
    return abs(ext_value - key_value) <= tol


def threshold_match(ext_cov, key_cov):
    """Threshold matches the key value or its waived alternative."""
    ext_value = (ext_cov or {}).get("threshold")
    if numbers_match(ext_value, key_cov.get("threshold")):
        return True
    waived = key_cov.get("waived_threshold")
    return waived is not None and numbers_match(ext_value, waived)


def fmt(value):
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return f"{value:.1f}"
    return str(value)


def score_company(ticker, key_entry, ext):
    """Return (rows, extra_names) for one company.

    Each row is a dict with covenant name, extracted/key actual and
    threshold, the two match flags, plus matched (value equals key),
    verified (quote passed), and matched_and_verified. An unverified
    match never counts as a verified result.
    """
    key_covs = (key_entry or {}).get("covenants", []) or []
    missing = ext is None
    ext_covs = (ext or {}).get("covenants", []) or []
    pairs, extras = match_covenants(key_covs, ext_covs)
    rows = []
    for key_cov, ext_cov in pairs:
        ext_cov = ext_cov or {}
        actual_ext = ext_cov.get("actual")
        actual_key = key_cov.get("actual")
        thresh_ext = ext_cov.get("threshold")
        thresh_key = key_cov.get("threshold")
        actual_ok = False if missing else numbers_match(actual_ext, actual_key)
        thresh_ok = False if missing else threshold_match(ext_cov, key_cov)
        matched = actual_ok and thresh_ok
        verified = False if missing else (ext_cov.get("quote_verified") is True)
        rows.append(
            {
                "ticker": ticker,
                "covenant": key_cov.get("name", "?"),
                "actual_ext": actual_ext,
                "actual_key": actual_key,
                "actual_match": actual_ok,
                "threshold_ext": thresh_ext,
                "threshold_key": thresh_key,
                "threshold_match": thresh_ok,
                "matched": matched,
                "verified": verified,
                "matched_and_verified": matched and verified,
            }
        )
    extra_names = [e.get("name", "?") for e in extras]
    return rows, extra_names


def print_table(rows):
    widths = {
        "ticker": max([len("company")] + [len(r["ticker"]) for r in rows]),
        "covenant": max([len("covenant")] + [len(r["covenant"]) for r in rows]),
        "actual": max(
            [len("actual ext vs key")]
            + [len(f"{fmt(r['actual_ext'])} vs {fmt(r['actual_key'])}") for r in rows]
        ),
        "threshold": max(
            [len("threshold ext vs key")]
            + [
                len(f"{fmt(r['threshold_ext'])} vs {fmt(r['threshold_key'])}")
                for r in rows
            ]
        ),
    }

    def yes(flag):
        return "yes" if flag else "no"

    header = (
        f"{'company':<{widths['ticker']}}  "
        f"{'covenant':<{widths['covenant']}}  "
        f"{'actual ext vs key':<{widths['actual']}}  "
        f"{'match':<5}  "
        f"{'threshold ext vs key':<{widths['threshold']}}  "
        f"{'match':<5}  "
        f"{'matched':<7}  "
        f"{'verified':<8}  "
        f"{'matched_and_verified':<20}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        actual = f"{fmt(r['actual_ext'])} vs {fmt(r['actual_key'])}"
        thresh = f"{fmt(r['threshold_ext'])} vs {fmt(r['threshold_key'])}"
        print(
            f"{r['ticker']:<{widths['ticker']}}  "
            f"{r['covenant']:<{widths['covenant']}}  "
            f"{actual:<{widths['actual']}}  "
            f"{yes(r['actual_match']):<5}  "
            f"{thresh:<{widths['threshold']}}  "
            f"{yes(r['threshold_match']):<5}  "
            f"{yes(r['matched']):<7}  "
            f"{yes(r['verified']):<8}  "
            f"{yes(r['matched_and_verified']):<20}"
        )


def main(argv=None, backtest_dir=BACKTEST_DIR):
    argv = sys.argv if argv is None else argv
    key = load_key(Path(backtest_dir) / "answer_key.json")
    tickers = sorted(key)
    if len(argv) > 1:
        want = [a.upper() for a in argv[1:]]
        unknown = [t for t in want if t not in key]
        if unknown:
            print(f"unknown ticker(s): {unknown}", file=sys.stderr)
            raise SystemExit(2)
        tickers = want

    all_rows = []
    for ticker in tickers:
        ext = load_disclosed(ticker, backtest_dir)
        if ext is None:
            print(f"note: {ticker} has no disclosed_{ticker}.json; all rows miss")
        rows, extras = score_company(ticker, key[ticker], ext)
        all_rows.extend(rows)
        for name in extras:
            print(f"note: {ticker} extra extraction not in key: {name}")

    if not all_rows:
        print("no covenants to score")
        return all_rows

    print_table(all_rows)

    n = len(all_rows)
    actual_ok = sum(1 for r in all_rows if r["actual_match"])
    thresh_ok = sum(1 for r in all_rows if r["threshold_match"])
    full_ok = sum(
        1 for r in all_rows if r["actual_match"] and r["threshold_match"]
    )
    matched_ok = sum(1 for r in all_rows if r["matched"])
    verified_ok = sum(1 for r in all_rows if r["verified"])
    both_ok = sum(1 for r in all_rows if r["matched_and_verified"])
    print(f"totals: {n} covenants")
    print(f"actual matched: {actual_ok}/{n}")
    print(f"threshold matched: {thresh_ok}/{n}")
    print(f"fully matched: {full_ok}/{n}")
    print(f"matched: {matched_ok}/{n}")
    print(f"verified: {verified_ok}/{n}")
    print(f"matched_and_verified: {both_ok}/{n}")
    return all_rows


if __name__ == "__main__":
    main()
