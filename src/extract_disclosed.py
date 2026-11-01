"""Extract disclosed covenant ratios from a 10-Q/10-K filing for the backtest.

For each case in data/backtest/companies.json: download the filing
(edgar.fetch, cached in data/raw), textify it, and send the full text
followed by extraction instructions in ONE chat request to Muse Spark
Open on Baseten (document first so the prefix can be cached). Parses
the JSON-only reply, runs one repair attempt per covenant whose
"quote" fails verification (follow-up request with the source text and
the failed quote, asking for the exact verbatim sentence containing
that number), re-verifies, records "quote_verified"/"repaired" on each
covenant, verifies every reported number's printed digits appear in the
source (reusing normalize and the number check from extract_release.py),
and saves the parsed JSON to data/backtest/disclosed_<TICKER>.json.

Cases with "local_doc" instead of "filing_url" (SNBR: delisted, use
the existing release data) read the local text file directly.

The answer key (data/backtest/answer_key.json) is NEVER read here; it
is used only by score_disclosed.py to score the extractor output.

Usage:
    python src/extract_disclosed.py [TICKER ...]
with no tickers extracting every case in companies.json.
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from openai import APIConnectionError, OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_release import (  # noqa: E402
    collect_quotes,
    format_thousands,
    normalize,
    strip_code_fences,
)
from edgar import fetch  # noqa: E402
from textify import html_to_text  # noqa: E402

load_dotenv(os.path.expanduser("~/.config/onya/.env"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPANIES_PATH = PROJECT_ROOT / "data" / "backtest" / "companies.json"
BACKTEST_DIR = PROJECT_ROOT / "data" / "backtest"

MODEL = "meta-models/muse-spark-open-1026"
MAX_TOKENS = 16000
TEMPERATURE = 0

SCHEMA = """{
 "period_end": "YYYY-MM-DD",
 "covenants": [{
   "name": str,
   "direction": "max"|"min",
   "threshold": number|null,
   "actual": number|null,
   "in_compliance": bool|null,
   "waiver_or_amendment_note": str|null,
   "quote": str
 }]
}"""

INSTRUCTIONS = """You are extracting disclosed financial-covenant compliance figures from the full SEC filing document above.

Return JSON ONLY matching this exact schema (no markdown, no commentary, no keys beyond the schema):

""" + SCHEMA + """

Cover:
- "period_end": the current period end date this filing reports, in YYYY-MM-DD format.
- "covenants": EVERY financial covenant (leverage ratios, coverage ratios, fixed charge tests, and similar) for which the filing discloses a required threshold, an actual ratio value, or a compliance statement. Report each distinct covenant once, in document order.

Rules:
- Every "quote" must be copied verbatim from the document above (max 40 words each). Copy the exact characters; do not paraphrase, fix, or normalize them. Keep all original punctuation.
- "name" is the covenant name as stated in the document (e.g. "total net leverage ratio", "interest coverage ratio").
- "direction" is "max" when the covenant requires the ratio to stay at or below the threshold (e.g. leverage not to exceed), and "min" when it must stay at or above the threshold (e.g. coverage not less than).
- "threshold" is the required level as a plain number (e.g. a 4.00x maximum becomes 4.0). Use null only when the filing states no threshold.
- "actual" is the disclosed actual ratio value as a plain number (e.g. 2.29). Use null only when the filing states no value (e.g. it only says the company was not in compliance).
- "in_compliance" is true/false from the filing's own compliance statement when given; otherwise infer it from actual vs threshold (true when the actual satisfies the direction); use null when neither a statement nor both numbers are available.
- "waiver_or_amendment_note" records any waiver, amendment, or modified threshold mentioned for that covenant (e.g. "waived to 1.75"), else null.
- Never infer or compute numbers. Only report values explicitly stated in the document.
- "period_end" must use YYYY-MM-DD format.

Return the JSON now."""

REPAIR_INSTRUCTIONS = """The quote above failed verification: it does not appear verbatim in the document.

Find the exact verbatim sentence from the document containing that number for this covenant. Copy characters exactly as printed: do not paraphrase, fix, or normalize anything. Keep all original punctuation and spacing.

Return ONLY that sentence, with no JSON, no markdown, no commentary, and no extra words."""


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


def cache_filename(case):
    """Deterministic data/raw filename for a case's filing download."""
    ticker = case["ticker"]
    base = os.path.basename(urlparse(case["filing_url"]).path) or "filing.htm"
    return f"backtest_{ticker}_{base}"


def fetch_document(case):
    """Return (source_text, source_label) for a backtest case.

    Filing cases download via edgar.fetch (cached) and are textified
    from HTML; local_doc cases (SNBR) read the existing text directly.
    """
    if case.get("filing_url"):
        path = fetch(case["filing_url"], cache_filename(case))
        return html_to_text(Path(path).read_bytes()), case["filing_url"]
    local = PROJECT_ROOT / case["local_doc"]
    return local.read_text(encoding="utf-8"), case["local_doc"]


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
    """Build one repair request: source text + failed quote + numbers.

    The model is asked for the exact verbatim sentence from the
    document containing that number, copied character-for-character.
    """
    failed_quote = covenant.get("quote", "")
    name = covenant.get("name", "?")
    threshold = covenant.get("threshold")
    actual = covenant.get("actual")
    numbers = f"threshold {threshold}, actual {actual}"
    return (
        document
        + "\n\n---\n\n"
        + f'Covenant "{name}" ({numbers}).\n'
        + f"FAILED QUOTE: {failed_quote}\n\n"
        + REPAIR_INSTRUCTIONS
    )


def parse_repair_quote(raw):
    """Extract the repaired quote from a repair response.

    The repair prompt asks for the bare sentence only, but accept a
    JSON {"quote": ...} reply (or a JSON string) for robustness.
    """
    text = strip_code_fences(raw or "").strip()
    if not text:
        return ""
    if text.startswith("{") or text.startswith('"'):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict) and isinstance(decoded.get("quote"), str):
            return decoded["quote"].strip()
        if isinstance(decoded, str):
            return decoded.strip()
    return text


def repair_quotes(parsed, document, client):
    """Repair each covenant whose quote fails verification, once.

    Sends at most one follow-up request per covenant with the source
    text and the failed quote, asking for the exact verbatim sentence
    containing that number. Re-verifies the replacement and records
    "quote_verified" (final quote state) and "repaired" (whether a
    repair attempt was made) on every covenant. Mutates parsed in
    place and returns it.
    """
    source_norm = normalize(document)
    covenants = parsed.get("covenants", []) or []
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


def number_in_source(value, source_norm):
    """True when a reported number's printed digits appear in the source.

    Same check as extract_release.check_number: the format_thousands
    rendering (and its comma-stripped form) must appear verbatim,
    plus plain-decimal renderings for ratio values.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    printed = format_thousands(value)
    candidates = {printed, printed.replace(",", ""), str(value)}
    if isinstance(value, float):
        candidates.add(f"{value:.2f}")
        candidates.add(f"{value:.2f}".rstrip("0").rstrip("."))
    return any(c and c in source_norm for c in candidates)


def verify(parsed, document):
    """Verify quotes and numbers against the source.

    Returns (verified, total, failures). Check 1: every "quote"
    appears in the source (normalized). Check 2: every reported
    threshold/actual number's printed digits appear in the source.
    """
    source_norm = normalize(document)
    failures = []
    verified = 0
    total = 0

    quotes = []
    collect_quotes(parsed, quotes)
    for q in quotes:
        total += 1
        q_norm = normalize(q)
        if q_norm and q_norm in source_norm:
            verified += 1
        else:
            failures.append(
                f"FAILED QUOTE: {q}" if q_norm else "FAILED QUOTE: empty quote"
            )

    for entry in parsed.get("covenants", []) or []:
        label = entry.get("name", "?")
        for field in ("threshold", "actual"):
            value = entry.get(field)
            if value is None:
                continue
            total += 1
            if number_in_source(value, source_norm):
                verified += 1
            else:
                failures.append(
                    f"FAILED NUMBER [{label} {field}]: {value!r} not in source"
                )
    return verified, total, failures


def print_usage(response):
    usage = response.usage
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    reasoning_tokens = None
    details = getattr(usage, "completion_tokens_details", None)
    if details is not None:
        reasoning_tokens = getattr(details, "reasoning_tokens", None)
    if reasoning_tokens is None:
        reasoning_tokens = getattr(usage, "reasoning_tokens", None)
    print(f"prompt tokens: {prompt_tokens}")
    print(f"completion tokens: {completion_tokens}")
    print(f"reasoning tokens: {reasoning_tokens}")


def disclosed_path(ticker, backtest_dir=BACKTEST_DIR):
    return Path(backtest_dir) / f"disclosed_{ticker}.json"


def extract_one(case, client, backtest_dir=BACKTEST_DIR):
    """Extract one case; save JSON + raw; return (parsed, verified, total, failures).

    Runs the repair pass (at most one follow-up request per covenant
    whose quote fails verification) before saving, so the saved JSON
    carries the repaired quotes plus "quote_verified"/"repaired" flags.
    """
    ticker = case["ticker"]
    document, label = fetch_document(case)
    print(f"=== {ticker} ({label}) ===")
    content = build_content(document)
    parsed, raw, response = parse_response(client, content)

    repair_quotes(parsed, document, client)

    backtest_dir = Path(backtest_dir)
    backtest_dir.mkdir(parents=True, exist_ok=True)
    json_path = disclosed_path(ticker, backtest_dir)
    raw_path = backtest_dir / f"disclosed_{ticker}_raw.txt"
    raw_path.write_text(raw, encoding="utf-8")
    json_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")

    verified, total, failures = verify(parsed, document)
    print(f"verified/total: {verified}/{total}")
    for failure in failures:
        print(failure)

    print_usage(response)
    print(f"saved: {json_path}")
    print(f"saved: {raw_path}")
    return parsed, verified, total, failures


def main(argv=None):
    argv = sys.argv if argv is None else argv
    companies = load_companies()
    if len(argv) > 1:
        want = {a.upper() for a in argv[1:]}
        companies = [c for c in companies if c["ticker"].upper() in want]
        missing = want - {c["ticker"].upper() for c in companies}
        if missing:
            print(f"unknown ticker(s): {sorted(missing)}", file=sys.stderr)
            raise SystemExit(2)
    client = make_client()
    for case in companies:
        extract_one(case, client)


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        print(f"missing environment variable: {exc}", file=sys.stderr)
        raise SystemExit(1)
