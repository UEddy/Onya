"""Compare base-agreement covenant thresholds against disclosed ones (backtest).

For each company in data/backtest/companies.json except SNBR: select
the base agreement via edgar.select_agreement as of period_end + 45
days, extract financial covenants from the base agreement with the
extract.py schema and prompt on Muse Spark Open via Baseten, repair
each failed financial-covenant quote once (recording quote_verified
and repaired), resolve each covenant's threshold schedule to the
value applicable at period_end (honoring step-down schedules and
"thereafter" entries, preferring entries whose condition is null and
reporting conditional ones as conditional_alternatives), and compare
with the disclosed thresholds in data/backtest/disclosed_<TICKER>.json,
matched by direction and name tokens like score_disclosed.py.

Saves data/backtest/terms_<TICKER>.json per company and prints a
table plus totals. A covenant amended after the agreement's filing
(like a waiver) is reported as "amended after agreement", not as a
miss, when the disclosure says so. Agreements over 900,000
characters are reported as "too long" instead of being truncated.

The answer key (data/backtest/answer_key.json) is NEVER read here;
only the disclosed_<TICKER>.json extractor outputs are compared
against.

Usage:
    python src/backtest_terms.py [--force] [--reverify] [TICKER ...]
with no tickers covering every company in companies.json except SNBR.
Companies whose terms_<TICKER>.json already exists are skipped unless
--force is given. A company that raises is recorded with status
"error" and the run continues. --reverify re-runs quote verification
plus failed-quote diagnostics from the saved raw output without
calling the model.
"""

import json
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from openai import APIConnectionError, OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent))
from edgar import DISCOVERY_SINCE, fetch, select_agreement  # noqa: E402
from extract import (  # noqa: E402
    INSTRUCTIONS,
    SCHEMA,
    collect_quotes,
    diagnose_failed_quote,
    format_diagnostic,
    normalize,
    strip_code_fences,
)
from extract_disclosed import (  # noqa: E402
    REPAIR_INSTRUCTIONS,
    parse_repair_quote,
)
from score_disclosed import (  # noqa: E402
    load_disclosed,
    match_covenants,
    name_tokens,
    numbers_match,
)
from textify import html_to_text  # noqa: E402

load_dotenv(os.path.expanduser("~/.config/onya/.env"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPANIES_PATH = PROJECT_ROOT / "data" / "backtest" / "companies.json"
BACKTEST_DIR = PROJECT_ROOT / "data" / "backtest"

MODEL = "meta-models/muse-spark-open-1026"
MAX_TOKENS = 32000
TEMPERATURE = 0

MAX_CHARS = 900_000
AS_OF_LAG_DAYS = 45
SKIP_TICKERS = frozenset({"SNBR"})

STATUS_OK = "ok"
STATUS_TOO_LONG = "too long"
STATUS_NO_AGREEMENT = "base agreement not found"
STATUS_ERROR = "error"

DIAGNOSTICS_MARKER = (
    "\n\n--- QUOTE DIAGNOSTICS (appended, not model output) ---\n"
)
PRINT_DIAGNOSTICS = 3

ROW_MATCH = "match"
ROW_MISMATCH = "mismatch"
ROW_AMENDED = "amended after agreement"
ROW_NO_DISCLOSED = "no disclosed match"

AMENDMENT_RE = re.compile(r"amend|waiv|modif", re.IGNORECASE)


def make_client():
    """OpenAI-compatible client for Muse Spark Open on Baseten."""
    return OpenAI(
        api_key=os.environ["BASETEN_API_KEY"],
        base_url=os.environ["BASETEN_BASE_URL"],
        timeout=120,
        max_retries=2,
    )


def load_companies(path=COMPANIES_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def as_of_for(period_end):
    """Selection cutoff: period_end plus 45 days, as YYYY-MM-DD."""
    return (
        date.fromisoformat(period_end) + timedelta(days=AS_OF_LAG_DAYS)
    ).isoformat()


def company_key(case):
    """Ticker or CIK identifying a backtest case for select_agreement."""
    return case.get("cik") or case["ticker"]


def agreement_cache_filename(ticker, url):
    """Deterministic data/raw filename for a base-agreement download.

    Mirrors edgar.find_credit_agreements cache names
    (<cik>_<accession>_<document>) so exhibits fetched during
    discovery are reused; falls back to a backtest_terms_ name for
    URLs outside the EDGAR archive layout.
    """
    parts = urlparse(url).path.strip("/").split("/")
    if "data" in parts:
        tail = parts[parts.index("data") + 1:]
        if len(tail) >= 3:
            cik, acc = tail[0], tail[1]
            if cik.isdigit() and acc.replace("-", "").isdigit():
                return f"{int(cik)}_{acc.replace('-', '')}_{tail[-1]}"
    base = os.path.basename(urlparse(url).path) or "agreement.htm"
    return f"backtest_terms_{ticker}_{base}"


def fetch_agreement(base, ticker):
    """Download (cached) and textify the base agreement exhibit."""
    url = base["url"]
    path = fetch(url, agreement_cache_filename(ticker, url))
    return html_to_text(Path(path).read_bytes()), url


def build_content(document):
    # Document first, instructions second, in a single message (cacheable prefix).
    return document + "\n\n---\n\n" + INSTRUCTIONS


REQUEST_RETRY_DELAYS = (5, 15, 30)


def request_completion(client, content):
    """One chat completion, retrying Baseten connection errors."""
    for attempt in range(len(REQUEST_RETRY_DELAYS) + 1):
        try:
            return client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": content}],
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
            )
        except APIConnectionError:
            if attempt == len(REQUEST_RETRY_DELAYS):
                raise
            time.sleep(REQUEST_RETRY_DELAYS[attempt])


def parse_response(client, content):
    """Request once, retry once on invalid JSON; return (parsed, raw, response)."""
    response = request_completion(client, content)
    raw = response.choices[0].message.content or ""
    try:
        parsed = json.loads(strip_code_fences(raw))
    except json.JSONDecodeError:
        response = request_completion(client, content)  # retry once
        raw = response.choices[0].message.content or ""
        parsed = json.loads(strip_code_fences(raw))  # raise if still invalid
    return parsed, raw, response


def quote_in_source(quote, source_norm):
    """True when a quote appears verbatim in the source (normalized)."""
    if not isinstance(quote, str):
        return False
    q_norm = normalize(quote)
    return bool(q_norm and q_norm in source_norm)


def build_repair_content(document, covenant):
    """Build one repair request: source text + failed quote + schedule.

    The model is asked for the exact verbatim sentence from the
    document containing the covenant's threshold number, copied
    character-for-character.
    """
    failed_quote = covenant.get("quote", "")
    name = covenant.get("name", "?")
    bits = []
    for entry in covenant.get("thresholds") or []:
        bit = f"{entry.get('value')}"
        when = entry.get("period_end") or entry.get("applies_after")
        if when:
            bit += f" as of {when}"
        if entry.get("condition"):
            bit += f" ({entry['condition']})"
        bits.append(bit)
    numbers = "thresholds " + (", ".join(bits) if bits else "?")
    return (
        document
        + "\n\n---\n\n"
        + f'Covenant "{name}" ({numbers}).\n'
        + f"FAILED QUOTE: {failed_quote}\n\n"
        + REPAIR_INSTRUCTIONS
    )


def repair_quotes(parsed, document, client):
    """Repair each financial covenant whose quote fails verification, once.

    Sends at most one follow-up request per covenant with the source
    text and the failed quote, asking for the exact verbatim sentence
    containing that number. Verification uses the shared normalize(),
    so formatting-only differences never trigger a repair.
    Re-verifies the replacement and records "quote_verified" (final
    quote state) and "repaired" (whether a repair attempt was made)
    on every financial covenant. Mutates parsed in place and returns
    it.
    """
    source_norm = normalize(document)
    covenants = parsed.get("financial_covenants", []) or []
    for entry in covenants:
        if quote_in_source(entry.get("quote"), source_norm):
            entry["quote_verified"] = True
            entry["repaired"] = False
            continue
        content = build_repair_content(document, entry)
        response = request_completion(client, content)
        raw = response.choices[0].message.content or ""
        new_quote = parse_repair_quote(raw)
        if new_quote:
            entry["quote"] = new_quote
        entry["quote_verified"] = quote_in_source(
            entry.get("quote"), source_norm
        )
        entry["repaired"] = True
    return parsed


def verify_quotes(parsed, document):
    """Verify every quote against the source (extract.py logic).

    Returns (verified, total, failures, per_covenant) where
    per_covenant aligns with parsed financial_covenants in order.
    """
    source_norm = normalize(document)
    quotes = []
    collect_quotes(parsed, quotes)
    failures = []
    verified = 0
    for q in quotes:
        if quote_in_source(q, source_norm):
            verified += 1
        else:
            failures.append(q)
    per_covenant = [
        quote_in_source(cov.get("quote"), source_norm)
        for cov in parsed.get("financial_covenants", []) or []
    ]
    return verified, len(quotes), failures, per_covenant


def diagnose_failures(failures, document):
    """Failed-quote diagnostics against the source (shared extract logic)."""
    if not failures:
        return []
    source_norm = normalize(document)
    return [diagnose_failed_quote(q, source_norm) for q in failures]


def print_diagnostics(diagnostics, raw_name=None):
    """Print the first PRINT_DIAGNOSTICS entries."""
    for i, diag in enumerate(diagnostics[:PRINT_DIAGNOSTICS], 1):
        print(format_diagnostic(diag, index=i))
    if len(diagnostics) > PRINT_DIAGNOSTICS:
        where = f" (see {raw_name})" if raw_name else ""
        print(f"... and {len(diagnostics) - PRINT_DIAGNOSTICS} more{where}")


def _resolve_entry(entries, period_end):
    """Date-resolution winner among threshold entries (or None).

    Exact dated entries win; otherwise the latest "thereafter" entry
    (period_end null) whose applies_after precedes period_end;
    otherwise the latest dated entry on/before period_end, or the
    earliest dated entry when period_end precedes the schedule.
    """
    dated = sorted(
        (t for t in entries if t.get("period_end")),
        key=lambda t: t["period_end"],
    )
    for entry in dated:
        if entry["period_end"] == period_end:
            return entry
    after = [
        t
        for t in entries
        if not t.get("period_end")
        and (t.get("applies_after") or "") < period_end
    ]
    if after:
        after.sort(key=lambda t: t.get("applies_after") or "")
        return after[-1]
    prior = [t for t in dated if t["period_end"] < period_end]
    if prior:
        return prior[-1]
    if dated:
        return dated[0]
    return None


def applicable_threshold(thresholds, period_end):
    """Threshold value in force at period_end (YYYY-MM-DD).

    Only entries whose condition is null are considered; conditional
    entries (e.g. a covenant holiday after an acquisition) are never
    chosen here -- see conditional_alternatives and condition_active.
    Date resolution among unconditional entries: exact dated entries
    win; otherwise a "thereafter" entry (period_end null) whose
    applies_after precedes period_end; otherwise the latest dated
    entry on/before period_end, or the earliest dated entry when
    period_end precedes the schedule. None when the schedule has no
    unconditional entry.
    """
    entries = [t for t in thresholds or [] if not t.get("condition")]
    entry = _resolve_entry(entries, period_end)
    return entry.get("value") if entry is not None else None


def conditional_alternatives(thresholds, period_end):
    """Conditional threshold entries in force at period_end.

    Returns [{"value", "condition"}] for the date-resolved winner
    among entries with a non-null condition (same date tiers as
    applicable_threshold), or [] when the schedule has no
    conditional entries.
    """
    entries = [t for t in thresholds or [] if t.get("condition")]
    entry = _resolve_entry(entries, period_end)
    if entry is None:
        return []
    return [{"value": entry.get("value"),
             "condition": entry.get("condition")}]


def condition_active(condition, value, dis_cov):
    """True when the disclosure explicitly says a condition is active.

    Requires both: the disclosure's stated threshold matches the
    conditional value, and its waiver/amendment note references the
    condition text. A note merely describing the condition
    hypothetically (with the base threshold stated) does not
    activate it.
    """
    if not condition or dis_cov is None:
        return False
    note = dis_cov.get("waiver_or_amendment_note")
    if not isinstance(note, str) or not note.strip():
        return False
    if not numbers_match(value, dis_cov.get("threshold")):
        return False
    return bool(name_tokens(note) & name_tokens(condition))


def disclosure_cites_amendment(dis_cov):
    """True when the disclosure notes a waiver/amendment for the covenant."""
    note = (dis_cov or {}).get("waiver_or_amendment_note")
    return isinstance(note, str) and bool(AMENDMENT_RE.search(note))


def score_terms(ticker, period_end, agreement_covs, disclosed_covs,
                agreement_url, quote_flags, repair_flags=None):
    """Compare agreement thresholds against disclosed ones.

    Each agreement covenant pairs with the best same-direction
    disclosed covenant by name tokens (score_disclosed matching); the
    agreement threshold is the schedule value applicable at
    period_end (unconditional entries only, unless the disclosure
    explicitly says a conditional alternative is active) and matches
    within 0.01. A mismatch whose disclosure cites an amendment or
    waiver is "amended after agreement", not a miss. Returns (rows,
    unmatched_disclosed_names).
    """
    pairs, extras = match_covenants(agreement_covs, disclosed_covs)
    rows = []
    for i, (agr_cov, dis_cov) in enumerate(pairs):
        thresholds = (agr_cov or {}).get("thresholds")
        agr_value = applicable_threshold(thresholds, period_end)
        alternatives = conditional_alternatives(thresholds, period_end)
        for alt in alternatives:
            if condition_active(alt["condition"], alt["value"], dis_cov):
                agr_value = alt["value"]
                break
        dis_value = (dis_cov or {}).get("threshold")
        if dis_cov is None:
            status = ROW_NO_DISCLOSED
            match = False
        elif numbers_match(agr_value, dis_value):
            status = ROW_MATCH
            match = True
        elif disclosure_cites_amendment(dis_cov):
            status = ROW_AMENDED
            match = False
        else:
            status = ROW_MISMATCH
            match = False
        rows.append(
            {
                "ticker": ticker,
                "name": (agr_cov or {}).get("name", "?"),
                "direction": (agr_cov or {}).get("direction"),
                "agreement_threshold": agr_value,
                "conditional_alternatives": alternatives,
                "disclosed_threshold": dis_value,
                "match": match,
                "quote_verified": quote_flags[i]
                if i < len(quote_flags)
                else False,
                "repaired": repair_flags[i]
                if repair_flags and i < len(repair_flags)
                else False,
                "status": status,
                "agreement_url": agreement_url,
            }
        )
    extra_names = [e.get("name", "?") for e in extras]
    return rows, extra_names


def terms_path(ticker, backtest_dir=BACKTEST_DIR):
    return Path(backtest_dir) / f"terms_{ticker}.json"


def save_record(record, backtest_dir):
    backtest_dir = Path(backtest_dir)
    backtest_dir.mkdir(parents=True, exist_ok=True)
    json_path = terms_path(record["ticker"], backtest_dir)
    json_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return json_path


def extract_one(case, client, backtest_dir=BACKTEST_DIR):
    """Run one company; save terms JSON (+ raw); return the record."""
    ticker = case["ticker"]
    period_end = case["period_end"]
    as_of = as_of_for(period_end)
    base, _amendments = select_agreement(company_key(case), as_of=as_of)
    if base is None:
        searched_range = f"{DISCOVERY_SINCE} to {as_of}"
        print(f"=== {ticker} (base agreement not found; "
              f"searched {searched_range}) ===")
        record = {
            "ticker": ticker,
            "period_end": period_end,
            "as_of": as_of,
            "agreement_url": None,
            "agreement_filing_date": None,
            "status": STATUS_NO_AGREEMENT,
            "searched_range": searched_range,
            "covenants": [],
            "unmatched_disclosed": [],
        }
        print(f"saved: {save_record(record, backtest_dir)}")
        return record

    url = base["url"]
    print(f"=== {ticker} ({url}) ===")
    document, _ = fetch_agreement(base, ticker)
    if len(document) > MAX_CHARS:
        print(f"base agreement too long: {len(document)} characters")
        record = {
            "ticker": ticker,
            "period_end": period_end,
            "as_of": as_of,
            "agreement_url": url,
            "agreement_filing_date": base.get("filingDate"),
            "status": STATUS_TOO_LONG,
            "covenants": [],
            "unmatched_disclosed": [],
        }
        print(f"saved: {save_record(record, backtest_dir)}")
        return record

    content = build_content(document)
    parsed, raw, _response = parse_response(client, content)
    repair_quotes(parsed, document, client)
    verified, total, failures, quote_flags = verify_quotes(parsed, document)
    diagnostics = diagnose_failures(failures, document)

    disclosed = load_disclosed(ticker, backtest_dir)
    if disclosed is None:
        print(f"note: {ticker} has no disclosed_{ticker}.json")
    disclosed_covs = (disclosed or {}).get("covenants", []) or []
    agreement_covs = parsed.get("financial_covenants", []) or []
    repair_flags = [bool(cov.get("repaired")) for cov in agreement_covs]
    rows, extra_names = score_terms(
        ticker, period_end, agreement_covs, disclosed_covs, url,
        quote_flags, repair_flags)
    for name in extra_names:
        print(f"note: {ticker} disclosed covenant not in agreement: {name}")

    record = {
        "ticker": ticker,
        "period_end": period_end,
        "as_of": as_of,
        "agreement_url": url,
        "agreement_filing_date": base.get("filingDate"),
        "status": STATUS_OK,
        "covenants": [
            {k: row[k] for k in (
                "name", "direction", "agreement_threshold",
                "conditional_alternatives", "disclosed_threshold",
                "match", "quote_verified", "repaired",
                "status", "agreement_url")}
            for row in rows
        ],
        "unmatched_disclosed": extra_names,
    }
    backtest_dir = Path(backtest_dir)
    raw_path = backtest_dir / f"terms_{ticker}_raw.txt"
    raw_text = raw
    if diagnostics:
        raw_text += DIAGNOSTICS_MARKER + json.dumps(diagnostics, indent=2) + "\n"
    raw_path.write_text(raw_text, encoding="utf-8")
    json_path = save_record(record, backtest_dir)

    print(f"verified/total: {verified}/{total}")
    for q in failures:
        print(f"FAILED QUOTE: {q if normalize(q) else 'empty quote'}")
    print_diagnostics(diagnostics, raw_name=raw_path.name)
    print(f"saved: {json_path}")
    print(f"saved: {raw_path}")
    return record


def error_record(case, exc):
    """Record for a company whose extraction raised."""
    ticker = case["ticker"]
    period_end = case.get("period_end", "")
    try:
        as_of = as_of_for(period_end) if period_end else None
    except ValueError:
        as_of = None
    return {
        "ticker": ticker,
        "period_end": period_end,
        "as_of": as_of,
        "agreement_url": None,
        "agreement_filing_date": None,
        "status": STATUS_ERROR,
        "error": f"{type(exc).__name__}: {exc}",
        "covenants": [],
        "unmatched_disclosed": [],
    }


def raw_terms_path(ticker, backtest_dir=BACKTEST_DIR):
    return Path(backtest_dir) / f"terms_{ticker}_raw.txt"


def reverify_terms(case, backtest_dir=BACKTEST_DIR):
    """Re-run verification + diagnostics from saved raw output (no model).

    Parses the leading JSON of terms_<TICKER>_raw.txt (ignoring any
    appended diagnostics), re-fetches the cached agreement text, and
    prints the report. Returns the report dict, or None when no raw
    output exists.
    """
    backtest_dir = Path(backtest_dir)
    ticker = case["ticker"]
    raw_path = raw_terms_path(ticker, backtest_dir)
    if not raw_path.exists():
        print(f"note: {ticker} has no {raw_path.name}")
        return None
    raw_text = raw_path.read_text(encoding="utf-8")
    parsed = json.JSONDecoder().raw_decode(raw_text.strip())[0]

    url = None
    json_path = terms_path(ticker, backtest_dir)
    if json_path.exists():
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        url = saved.get("agreement_url")
    if url is None:
        base, _amendments = select_agreement(
            company_key(case), as_of=as_of_for(case["period_end"]))
        if base is None:
            print(f"note: {ticker} has no agreement to verify against")
            return None
        url = base["url"]
    document, _ = fetch_agreement({"url": url}, ticker)

    verified, total, failures, quote_flags = verify_quotes(parsed, document)
    diagnostics = diagnose_failures(failures, document)
    print(f"=== {ticker} (reverify, no model calls) ===")
    print(f"verified/total: {verified}/{total}")
    covenants = parsed.get("financial_covenants", []) or []
    for i, cov in enumerate(covenants):
        flag = quote_flags[i] if i < len(quote_flags) else False
        print(f"  [{'yes' if flag else 'no'}] {cov.get('name', '?')}")
    for q in failures:
        print(f"FAILED QUOTE: {q if normalize(q) else 'empty quote'}")
    print_diagnostics(diagnostics)
    return {
        "ticker": ticker,
        "agreement_url": url,
        "verified": verified,
        "total": total,
        "failures": failures,
        "diagnostics": diagnostics,
    }


def fmt(value):
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return f"{value:.1f}"
    return str(value)


def print_table(rows):
    widths = {
        "ticker": max([len("company")] + [len(r["ticker"]) for r in rows]),
        "covenant": max([len("covenant")] + [len(r["name"]) for r in rows]),
        "threshold": max(
            [len("agreement vs disclosed")]
            + [
                len(f"{fmt(r['agreement_threshold'])}"
                    f" vs {fmt(r['disclosed_threshold'])}")
                for r in rows
            ]
        ),
        "status": max([len("status")] + [len(r["status"]) for r in rows]),
    }

    def yes(flag):
        return "yes" if flag else "no"

    header = (
        f"{'company':<{widths['ticker']}}  "
        f"{'covenant':<{widths['covenant']}}  "
        f"{'agreement vs disclosed':<{widths['threshold']}}  "
        f"{'match':<5}  "
        f"{'verified':<8}  "
        f"{'status':<{widths['status']}}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        thresh = (f"{fmt(r['agreement_threshold'])}"
                  f" vs {fmt(r['disclosed_threshold'])}")
        print(
            f"{r['ticker']:<{widths['ticker']}}  "
            f"{r['name']:<{widths['covenant']}}  "
            f"{thresh:<{widths['threshold']}}  "
            f"{yes(r['match']):<5}  "
            f"{yes(r['quote_verified']):<8}  "
            f"{r['status']:<{widths['status']}}"
        )


def main(argv=None, backtest_dir=BACKTEST_DIR):
    argv = sys.argv if argv is None else argv
    args = list(argv[1:])
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    reverify = "--reverify" in args
    args = [a for a in args if a != "--reverify"]
    unknown_flags = [a for a in args if a.startswith("--")]
    if unknown_flags:
        print(f"unknown flag(s): {unknown_flags}", file=sys.stderr)
        raise SystemExit(2)

    companies = [c for c in load_companies()
                 if c["ticker"].upper() not in SKIP_TICKERS]
    if args:
        want = [a.upper() for a in args]
        known = {c["ticker"].upper() for c in load_companies()}
        unknown = [t for t in want if t not in known]
        if unknown:
            print(f"unknown ticker(s): {unknown}", file=sys.stderr)
            raise SystemExit(2)
        skipped = [t for t in want if t in SKIP_TICKERS]
        for t in skipped:
            print(f"note: {t} skipped (SNBR excluded from terms backtest)")
        companies = [c for c in companies if c["ticker"].upper() in want]

    if not companies:
        print("no companies to run")
        return []

    if reverify:
        return [r for c in companies
                if (r := reverify_terms(c, backtest_dir)) is not None]

    backtest_dir = Path(backtest_dir)
    need_client = force or any(
        not terms_path(c["ticker"], backtest_dir).exists()
        for c in companies)
    client = make_client() if need_client else None
    records = []
    for case in companies:
        json_path = terms_path(case["ticker"], backtest_dir)
        if json_path.exists() and not force:
            print(f"note: {case['ticker']} already done, skipping "
                  f"(use --force to re-run)")
            records.append(
                json.loads(json_path.read_text(encoding="utf-8")))
            continue
        try:
            records.append(extract_one(case, client, backtest_dir))
        except Exception as exc:
            record = error_record(case, exc)
            print(f"error: {case['ticker']}: {exc}")
            print(f"saved: {save_record(record, backtest_dir)}")
            records.append(record)

    all_rows = []
    for record in records:
        for cov in record.get("covenants", []):
            row = dict(cov)
            row["ticker"] = record["ticker"]
            all_rows.append(row)

    for record in records:
        if record.get("status") != STATUS_OK:
            print(f"note: {record['ticker']} status: {record['status']}")

    if not all_rows:
        print("no covenants to score")
        return records

    print_table(all_rows)

    n = len(all_rows)
    matched = sum(1 for r in all_rows if r["match"])
    amended = sum(1 for r in all_rows if r["status"] == ROW_AMENDED)
    no_disclosed = sum(
        1 for r in all_rows if r["status"] == ROW_NO_DISCLOSED)
    verified = sum(1 for r in all_rows if r["quote_verified"])
    mismatched = n - matched - amended - no_disclosed
    print(f"totals: {n} covenants across {len(records)} companies")
    print(f"matched: {matched}/{n}")
    print(f"amended after agreement: {amended}")
    print(f"no disclosed match: {no_disclosed}")
    print(f"mismatched: {mismatched}")
    print(f"quote verified: {verified}/{n}")
    return records


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        print(f"missing environment variable: {exc}", file=sys.stderr)
        raise SystemExit(1)
