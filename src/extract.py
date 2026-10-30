"""Extract financial covenants and definitions from the SNBR 13th amendment.

Sends the full document followed by extraction instructions in ONE chat
request (document first so the prefix can be cached), parses the JSON-only
reply, verifies every "quote" appears verbatim in the source, and saves
the parsed JSON plus the raw response.
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
DOC_PATH = PROJECT_ROOT / "data" / "extracted" / "snbr_13th_amendment.txt"
JSON_PATH = PROJECT_ROOT / "data" / "extracted" / "snbr_covenants.json"
RAW_PATH = PROJECT_ROOT / "data" / "extracted" / "snbr_raw_response.txt"

MODEL = "muse-spark-1.3"
MAX_TOKENS = 32000
TEMPERATURE = 0

SCHEMA = """{
 "borrower": str,
 "agreement": {"title": str, "dated": str, "administrative_agent": str},
 "financial_covenants": [{
   "id": str, "name": str, "section": str, "direction": "max"|"min",
   "metric_term": str,
   "unit": "ratio"|"percent_of_forecast"|"usd",
   "thresholds": [{"period_end": "YYYY-MM-DD"|null, "applies_after": "YYYY-MM-DD"|null, "value": number, "condition": str|null}],
   "quote": str }],
 "cap_groups": [{
   "id": str, "applies_to_clauses": [str],
   "schedule": [{"period_end": "YYYY-MM-DD"|null, "applies_after": "YYYY-MM-DD"|null, "amount_usd": number, "condition": str|null}],
   "quote": str }],
 "definitions": [{
   "term": str, "section": str, "formula_summary": str,
   "components": [{
     "label": str, "sign": "+"|"-", "clause_ref": str,
     "cap_group_id": str|null,
     "requires_agent_approval": bool,
     "publicly_verifiable": "yes"|"partial"|"no",
     "quote": str }],
   "quote": str }],
 "specified_defaults": [{"covenant_id": str, "period_end": "YYYY-MM-DD", "description": str, "quote": str}],
 "uncertainties": [str]
}"""

INSTRUCTIONS = """You are extracting financial covenant data from the full credit-agreement document above.

Return JSON ONLY matching this exact schema (no markdown, no commentary, no extra keys):

""" + SCHEMA + """

Rules:
- Every "quote" must be copied verbatim from the document above (max 40 words each). Copy the exact characters; do not paraphrase, fix, or normalize them. Keep all original punctuation and Unicode characters, including the curly quotation marks around defined terms (e.g. copy “Consolidated EBITDA” means exactly as written, never with straight " quotes and never without quotes).
- Never infer or compute numbers. Only report values explicitly stated in the document.
- Use null when something is not stated (e.g. a missing condition).
- Include every period in each threshold schedule and in each cap-group schedule. Do not summarize, truncate, or sample the schedules.
- A cap that limits several clauses in aggregate must be ONE cap group listing all those clauses in "applies_to_clauses". Never split an aggregate cap into one group per clause. Each capped component links to its group via "cap_group_id".
- For dated periods set "period_end" to the date and "applies_after" to null. For an "each period thereafter" entry set "period_end" to null and "applies_after" to the YYYY-MM-DD of the last dated period it follows, so no entry has a null date without meaning.
- "unit" is "ratio" for a pure ratio (e.g. leverage, coverage), "percent_of_forecast" for a test measured against forecast (the Consolidated Adjusted EBITDA test is 90 percent of forecast, so unit "percent_of_forecast" with value 90, never "usd" with value 90), and "usd" for a dollar amount.
- Capture any condition on a threshold or cap amount in "condition" (e.g. the $4,000,000 cap for the period ending January 2, 2027 applies only if One Hundred Percent Lender Consent has been obtained).
- Cover at least: the Net Leverage Ratio covenant, the Interest Coverage Ratio covenant, the minimum Consolidated Adjusted EBITDA test, and the definitions of Consolidated EBITDA, Consolidated EBITDAR, Consolidated Funded Indebtedness, Net Leverage Ratio, Interest Coverage Ratio, Indebtedness, Consolidated Rent Expense, Consolidated Interest Expense, Consolidated Net Earnings, and Liquidity.
- For ratio definitions, the formula_summary must state the numerator and denominator explicitly, including any rent, lease, or cash adjustments.
- "period_end" and "applies_after" must use YYYY-MM-DD format when not null.
- "direction" must be "max" or "min". "unit" must be "ratio", "percent_of_forecast", or "usd". "sign" must be "+" or "-". "publicly_verifiable" must be "yes", "partial", or "no".
- List anything ambiguous or not found in "uncertainties".

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


def main():
    document = DOC_PATH.read_text(encoding="utf-8")
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

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(raw, encoding="utf-8")
    JSON_PATH.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")

    quotes = []
    collect_quotes(parsed, quotes)
    source_norm = normalize(document)
    failures = []
    verified = 0
    for q in quotes:
        q_norm = normalize(q)
        if q_norm and q_norm in source_norm:
            verified += 1
        else:
            failures.append(q)
    total = len(quotes)
    print(f"verified/total: {verified}/{total}")
    for q in failures:
        print(f"FAILED QUOTE: {q}")

    print_usage(response)
    print(f"saved: {JSON_PATH}")
    print(f"saved: {RAW_PATH}")


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        print(f"missing environment variable: {exc}", file=sys.stderr)
        raise SystemExit(1)
