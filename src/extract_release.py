"""Extract TTM Adjusted EBITDA and net leverage figures from an SNBR earnings release.

Sends the full release text followed by extraction instructions in ONE chat
request (document first so the prefix can be cached), parses the JSON-only
reply, verifies every "quote" appears verbatim in the source and every
reported number's printed digits appear in the source, and saves the
parsed JSON plus the raw response.
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.expanduser("~/.config/onya/.env"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOC_PATH = PROJECT_ROOT / "data" / "extracted" / "snbr_earnings_q3_2025.txt"

MODEL = "muse-spark-1.3-contributor"
MAX_TOKENS = 16000
TEMPERATURE = 0

SCHEMA = """{
 "period_end": "YYYY-MM-DD",
 "adjusted_ebitda_ttm": [{"line": str, "value_thousands": number, "quote": str}],
 "leverage_table_ttm": [{"line": str, "value_thousands": number|null, "ratio": str|null, "quote": str}],
 "footnotes": [{"text": str, "quote": str}]
}"""

INSTRUCTIONS = """You are extracting figures from the full earnings-release document above.

Return JSON ONLY matching this exact schema (no markdown, no commentary, no extra keys):

""" + SCHEMA + """

Cover:
- "period_end": the current period end date (the quarter this release reports), in YYYY-MM-DD format.
- "adjusted_ebitda_ttm": EVERY line of the trailing-twelve-month (TTM) column of the "Adjusted EBITDA" reconciliation table, in table order, with values in thousands exactly as printed (e.g. printed "56,706" becomes 56706). Preserve the sign: values shown as subtractions, in parentheses, or with a minus sign are negative numbers.
- "leverage_table_ttm": EVERY line of the current-period column of the "Calculation of Net Leverage Ratio" table, in table order. Use "value_thousands" for dollar amounts (in thousands, as printed) and "ratio" for any ratio shown on that line (copied exactly as printed, e.g. "4.2x"), otherwise null.
- "footnotes": every footnote attached to either table, with "text" as the full footnote text and "quote" copied verbatim.

Rules:
- Every "quote" must be copied verbatim from the document above (max 40 words each). Copy the exact characters; do not paraphrase, fix, or normalize them. Keep all original punctuation.
- "line" labels must be copied as printed in the table.
- Cover the TTM column (Adjusted EBITDA reconciliation) and the current-period column (Net Leverage Ratio table) ONLY. Ignore all other periods and columns.
- Never infer or compute numbers. Only report values explicitly stated in the document.
- Use null when something is not stated (e.g. a line with no dollar amount or no ratio).
- "period_end" must use YYYY-MM-DD format.

Return the JSON now."""


def strip_code_fences(text):
    """Remove surrounding markdown code fences if present."""
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        lines = lines[1:]  # drop opening fence (``` or ```json)
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def collect_quotes(obj, out):
    """Recursively collect every value stored under a "quote" key."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "quote" and isinstance(value, str):
                out.append(value)
            else:
                collect_quotes(value, out)
    elif isinstance(obj, list):
        for item in obj:
            collect_quotes(item, out)


def normalize(text):
    """Collapse whitespace runs and map curly quotes to straight quotes.

    Applied to BOTH the model quote and the source, so verification does
    not depend on the model's quote style.
    """
    for curly, straight in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'")):
        text = text.replace(curly, straight)
    return re.sub(r"\s+", " ", text).strip()


def format_thousands(value):
    """Format a numeric value as printed in the release (e.g. 56706 -> "56,706")."""
    v = abs(value)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:,}"


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


def resolve_doc_path():
    if len(sys.argv) <= 1:
        return DEFAULT_DOC_PATH
    p = Path(sys.argv[1]).expanduser()
    if not p.is_absolute() and not p.exists():
        candidate = PROJECT_ROOT / p
        if candidate.exists():
            return candidate
    return p


def main():
    doc_path = resolve_doc_path()
    document = doc_path.read_text(encoding="utf-8")
    # Document first, instructions second, in a single message (cacheable prefix).
    content = document + "\n\n---\n\n" + INSTRUCTIONS

    client = OpenAI(
        api_key=os.environ["META_API_KEY"],
        base_url=os.environ["META_BASE_URL"],
    )

    def request():
        return client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )

    response = request()
    raw = response.choices[0].message.content or ""
    try:
        parsed = json.loads(strip_code_fences(raw))
    except json.JSONDecodeError:
        response = request()  # retry once
        raw = response.choices[0].message.content or ""
        parsed = json.loads(strip_code_fences(raw))  # raise if still invalid

    period_end = parsed.get("period_end", "unknown")
    json_path = PROJECT_ROOT / "data" / "extracted" / f"snbr_release_{period_end}.json"
    raw_path = PROJECT_ROOT / "data" / "extracted" / f"snbr_release_{period_end}_raw.txt"

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw, encoding="utf-8")
    json_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")

    source_norm = normalize(document)
    failures = []
    verified = 0
    total = 0

    # Check 1: every quote appears in the source (normalized).
    quotes = []
    collect_quotes(parsed, quotes)
    for q in quotes:
        total += 1
        q_norm = normalize(q)
        if q_norm and q_norm in source_norm:
            verified += 1
        else:
            failures.append(f"FAILED QUOTE: {q}")

    # Check 2: every reported number's printed digits appear in the source.
    def check_number(label, value):
        nonlocal verified, total
        total += 1
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            failures.append(f"FAILED NUMBER [{label}]: non-numeric value {value!r}")
            return
        printed = format_thousands(value)
        plain = printed.replace(",", "")
        if printed in source_norm or plain in source_norm:
            verified += 1
        else:
            failures.append(f"FAILED NUMBER [{label}]: {printed} (value {value}) not in source")

    def check_ratio(label, ratio):
        nonlocal verified, total
        total += 1
        r_norm = normalize(str(ratio))
        if r_norm and r_norm in source_norm:
            verified += 1
        else:
            failures.append(f"FAILED RATIO [{label}]: {ratio!r} not in source")

    for entry in parsed.get("adjusted_ebitda_ttm", []) or []:
        check_number(entry.get("line", "?"), entry.get("value_thousands"))

    for entry in parsed.get("leverage_table_ttm", []) or []:
        label = entry.get("line", "?")
        if entry.get("value_thousands") is not None:
            check_number(label, entry.get("value_thousands"))
        if entry.get("ratio") is not None:
            check_ratio(label, entry.get("ratio"))

    print(f"verified/total: {verified}/{total}")
    for failure in failures:
        print(failure)

    print_usage(response)
    print(f"saved: {json_path}")
    print(f"saved: {raw_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        print(f"missing environment variable: {exc}", file=sys.stderr)
        raise SystemExit(1)
