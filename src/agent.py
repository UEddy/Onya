"""Muse Spark tool-calling agent over Onya's covenant modules.

Onya monitors credit-facility covenants for a credit analyst: it finds the
governing credit agreement, extracts its financial covenants, computes
covenant ratios from SEC filings, projects the next test, analyzes cures,
and drafts watchlist memos.

Each tool is a thin wrapper over an existing module and returns compact
JSON (summaries and schedules, never whole documents). The agent loop runs
at most 15 tool calls per run, stops if total tokens exceed 400,000, and
logs every step to ``data/runs/<run_id>.jsonl`` (the UI's live agent log).

Run from the project root::

    python src/agent.py "Check Sleep Number's covenants as of the April 2026 test and tell me what to do."
"""

import concurrent.futures
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent))

import covenant  # noqa: E402
import cure  # noqa: E402
import project  # noqa: E402
import textify  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"

MODEL = "muse-spark-1.3"
TIER = "standard"  # base model name selects the standard tier (vs -contributor)
MAX_TOKENS = 8000  # per agent turn
MAX_TOOL_CALLS = 15
TOKEN_BUDGET = 400_000  # per run
TOOL_TIMEOUT_SECONDS = 45  # per tool call; a timeout becomes an error step

USAGE = 'Usage: python src/agent.py "<request>"'

SYSTEM_PROMPT = """You are Onya, a covenant-monitoring assistant for a credit analyst. You watch \
borrowers' credit-facility covenants: you find the governing credit agreement, extract its \
financial covenants, compute covenant ratios from SEC filings, project the next test, \
analyze cures, and draft watchlist memos.

You have these tools (call them; do not answer from memory):
- lookup_company(name_or_ticker, as_of?): resolve a company name or ticker to its \
CIK, even for delisted companies (local registry, then the SEC ticker list, then \
EDGAR company-name search). Returns candidates with cik, name, and source.
- find_agreements(company, as_of?): locate the base credit agreement and later amendments \
via EDGAR. Returns compact metadata only, newest first. Accepts a name, ticker, or CIK.
- extract_covenants(company, agreement_url, as_of?): download, textify, LLM-extract, and \
quote-verify a credit agreement. Returns thresholds, cap groups, definition terms, \
the equity_cure field, verification counts, and the saved path. Prefers an existing \
reviewed extraction when one is available.
- compute_covenants(company, period_end, as_of?): covenant ratios, thresholds, headroom, \
pass/fail, flags, labels, and scenarios. SNBR only for now.
- project_next_test(company, base_period, as_of?): baseline projection to the next Net \
Leverage test with cushions, trend risk, and backtest. SNBR only for now.
- cure_analysis(company, period_end, as_of?): dollar cure figures per covenant plus \
equity-cure status from the reviewed file's equity_cure field. SNBR only for now.
- draft_memo(company, period_end, draft, as_of?): submit your watchlist memo prose in the \
'draft' argument; every number, amendment ordinal, and document title in it is verified \
against prior tool outputs and any invented figure is flagged. Always call this before \
giving a final memo.

Rules:
- As-of discipline: every tool takes an as_of date (YYYY-MM-DD) and ignores \
information dated after it. When the user names a test period, call find_agreements \
with as_of = period_end + 45 days (the reporting window), and pass that same as_of \
to every other tool call in the run.
- When a tool fails, read the error message and try a different approach (for \
example, call lookup_company to resolve the company and retry with the CIK) \
before giving up.
- Always cite tool outputs for facts and figures. Never invent numbers.
- Every number in the memo must come from a tool result. Tool call arguments keep \
dates as YYYY-MM-DD, but memo prose uses dates like "Apr 4, 2026", ratios like \
"6.58x", and dollars like "$267.2 million" in prose; exact dollar figures with \
commas belong in the Covenant tests table.
- Describe documents and figures only with the exact titles and labels from tool \
outputs; never name or number an amendment yourself (no invented "first amendment", \
"13th amendment", or document title).
- When compute_covenants reports that no company leverage table was \
disclosed, rewrite it in your own words, for example "The company did not \
disclose a leverage table this quarter, so no reconciliation is available." \
Never copy raw tool status strings into the memo, and never write "no break".
- Report equity-cure status only from the reviewed file's equity_cure field. \
When equity_cure.present is false, write exactly "No equity cure provision \
was found in the reviewed agreement". Never write "the reviewed agreement \
provides no equity cure" or "no equity cure available": the extraction can \
only show that none was found.
- Spell out small counts ("two covenants") instead of using digits that never appeared \
in tool outputs.
- If a tool says "unsupported" (anything beyond SNBR for compute/project/cure), say \
"unsupported" honestly and stop that line of inquiry.
- Prefer reviewed extractions and filed results over estimates.
- Keep going until the user's question is answered or you run out of tool calls \
(15 max), then summarize.

Memo (the draft you submit to draft_memo, and your final answer):
- The reader is a credit analyst at the lender. Never advise "engaging lenders" \
or asking the lender to act. Recommended actions are lender actions, for \
example: reserve rights under the agreement, request the compliance certificate \
and support for each add-back, and tighten reporting.
- Use governing_doc_type from find_agreements. When it is "forbearance", do \
not recommend opening forbearance or amendment discussions. Recommend instead: \
review the forbearance terms, termination events, and expiry date against the \
next test; reserve rights; request the compliance certificate and add-back \
support; and tighten reporting. Do not invent the expiry date: say "check the \
forbearance expiry date" unless the extraction states it. Only when \
governing_doc_type is "amendment" or "base" may you recommend amendment \
discussions with the borrower.
- Use these short headings, in this order: Summary, Covenant tests, What drove \
it, Cure, Outlook, Recommended actions. Summary is two sentences.
- Under Covenant tests, give a small markdown table with columns Covenant, \
Result, Limit, Headroom. Exact figures go in this table.
- Build every What drove it sentence only from that covenant's \
numerator_label, numerator_value, denominator_label, and denominator_value. \
Net leverage uses total debt including operating leases over Consolidated \
EBITDAR. Interest coverage uses Consolidated EBITDA over Consolidated Interest \
Expense. Never pair Consolidated EBITDAR with interest.
- Always report projected-savings scenarios when scenarios are present, and \
write each covenant once: "Net leverage is 5.06x even with the maximum $44M \
of projected savings, and 6.58x without." Use the same single-sentence form \
for interest coverage, with its own ratios.
- When avg_quarterly_change is present, report its value and name the method \
in plain words, for example "endpoint to endpoint". Do not present \
trend_avg_decline as the average quarterly change.
- When a projected cushion is negative, do not call the cushion negative. Say \
"EBITDAR would need to rise by $54.1 million to pass the Jul 4, 2026 test at \
the baseline projection", using the shortfall field and next test date from \
the tool output.
- End with Recommended actions as three to five bullets, each a lender action.
- After a test date, use the plural noun "failures", as in "Reserve rights \
under the agreement for the Apr 4, 2026 failures", never "the Apr 4, 2026 \
fails".
- Format ratios always with two decimals and x, such as 2.10x, 4.80x, and \
1.70x. Write risk in lowercase, such as "high risk". Write "add-backs" \
hyphenated. Use sentence case covenant names in prose, such as "net leverage" \
and "interest coverage"; the table may keep the agreement's defined terms.
- Write document titles in sentence case, never ALL CAPS. Use plain words: \
write "fails", not "result fail". Use no em dashes anywhere.
"""

SUPPORTED_PIPELINES = frozenset({"snbr"})

REPORTING_WINDOW_DAYS = 45

RECONCILIATION_UNAVAILABLE = (
    "not available (no company leverage table disclosed)"
)


def reporting_as_of(period_end):
    """Knowledge cutoff for a named test period: period_end + 45 days.

    The reporting window covers the quarter-end plus the filing lag, so
    find_agreements (and every other tool in the run) sees filings
    available to the analyst at that point and nothing later.
    """
    return (datetime.strptime(str(period_end)[:10], "%Y-%m-%d").date()
            + timedelta(days=REPORTING_WINDOW_DAYS)).isoformat()


def _period_after_as_of(period, as_of):
    """True when a requested period_end is dated after the as_of cutoff."""
    if not period or not as_of:
        return False
    return str(period)[:10] > str(as_of)[:10]

_KNOWN_COMPANIES = {
    "snbr": ("snbr", "SNBR"),
    "sleep number": ("snbr", "SNBR"),
    "sleep number corp": ("snbr", "SNBR"),
    "sleep number corporation": ("snbr", "SNBR"),
    "select comfort": ("snbr", "SNBR"),
}


def _normalize_company(company):
    return re.sub(r"\s+", " ", str(company or "").strip().lower())


def _cik_digits(cik):
    return "".join(ch for ch in str(cik or "") if ch.isdigit())


def _cik_plain(cik):
    digits = _cik_digits(cik)
    if not digits:
        return ""
    return str(int(digits))


def _cik10(cik):
    digits = _cik_digits(cik)
    if not digits:
        return ""
    return digits.zfill(10)[-10:]


def _load_companies_registry():
    """Local ticker/name -> CIK registry (covers delisted companies)."""
    try:
        path = DATA_DIR / "companies.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _registry_slug_for_cik(plain_cik):
    """Slug of the registry entry matching a plain CIK, else None."""
    if not plain_cik:
        return None
    for key, info in _load_companies_registry().items():
        if not isinstance(info, dict):
            continue
        if _cik_plain(info.get("cik")) == plain_cik:
            slug = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if slug:
                return slug
    return None


def _registry_slug_for_name(query):
    """Slug of the registry entry matching a company name, else None."""
    ql = _normalize_company(query)
    if not ql:
        return None
    for key, info in _load_companies_registry().items():
        if not isinstance(info, dict):
            continue
        name = _normalize_company(info.get("name") or "")
        if not name:
            continue
        if ql == name or ql in name or name in ql:
            slug = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if slug:
                return slug
    return None


def company_slug(company):
    """Short lowercase slug used for file names (e.g. "snbr").

    Accepts a name, ticker, or CIK (with or without leading zeros). CIKs
    and names registered in data/companies.json resolve to their entry.
    """
    key = _normalize_company(company)
    if key in _KNOWN_COMPANIES:
        return _KNOWN_COMPANIES[key][0]
    tok = str(company or "").strip()
    if tok.isdigit():
        slug = _registry_slug_for_cik(_cik_plain(tok))
        if slug:
            return slug
        return _cik_plain(tok) or "unknown"
    slug = _registry_slug_for_name(tok)
    if slug:
        return slug
    return re.sub(r"[^a-z0-9]", "", key) or "unknown"


def resolve_ticker(company):
    """Resolve a company name to a ticker symbol or CIK for EDGAR lookup.

    Accepts a ticker, a numeric CIK, or a company name. Unknown names are
    resolved through lookup_company (registry, SEC ticker list, EDGAR
    name search) and return the best-match CIK.
    """
    key = _normalize_company(company)
    if key in _KNOWN_COMPANIES:
        return _KNOWN_COMPANIES[key][1]
    tok = str(company or "").strip()
    if re.fullmatch(r"[A-Za-z]{1,5}(\.[A-Za-z]{1,2})?", tok):
        return tok.upper()
    if tok.isdigit():
        return tok
    try:
        found = tool_lookup_company(tok)
    except Exception:
        found = None
    cands = (found or {}).get("candidates") or []
    if cands and cands[0].get("cik"):
        return cands[0]["cik"]
    raise ValueError(
        f"cannot resolve {company!r} to a ticker or CIK; "
        "pass a ticker symbol (e.g. SNBR) or a numeric CIK"
    )


# ---------------------------------------------------------------------------
# Tool-output corpus (powers draft_memo number verification)
# ---------------------------------------------------------------------------

_TOOL_OUTPUTS = []


def _record(result):
    """Append a JSON-detached copy of a tool result to the run corpus."""
    _TOOL_OUTPUTS.append(json.loads(json.dumps(result, default=str)))
    return result


def reset_corpus():
    """Clear the tool-output corpus (called at the start of each run)."""
    _TOOL_OUTPUTS.clear()


# ---------------------------------------------------------------------------
# Number verification for draft memos
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MONTH_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(\d{1,2}),\s+(\d{4})")
_MONTH_NUMBERS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5,
                  "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10,
                  "Nov": 11, "Dec": 12}
NUMBER_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"  # ISO date first, so it stays one token
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"\d{1,2},\s+\d{4}"  # "Apr 4, 2026" stays one date token
    r"|(?<![A-Za-z0-9/])\$?\d[\d,]*(?:\.\d+)?"  # number, optional $/commas/decimals
    r"%?"  # optional percent
    r"(?:\s?(?:x|million|billion|thousand|[KMB]))?"  # optional ratio/scale suffix
)

_SCALE_MULTIPLIERS = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "million": 1e6,
    "b": 1e9, "billion": 1e9,
}
_SUFFIX_RE = re.compile(r"^(.*?)\s*(%|x|X|million|billion|thousand|[KMB])?$")


def _parse_number_token(token):
    """Parse one regex token into (text, value, tolerance) for matching."""
    t = token.strip()
    if DATE_RE.fullmatch(t):
        return {"raw": token, "kind": "date", "text": t, "value": None,
                "tolerance": 0.0}
    month_match = MONTH_DATE_RE.fullmatch(t)
    if month_match:
        month = _MONTH_NUMBERS[month_match.group(1)]
        iso = "%s-%02d-%02d" % (month_match.group(3), month,
                                int(month_match.group(2)))
        return {"raw": token, "kind": "date", "text": iso, "value": None,
                "tolerance": 0.0}
    t = t.replace("$", "").replace(",", "").strip()
    m = _SUFFIX_RE.match(t)
    core, suffix = m.group(1).strip(), (m.group(2) or "")
    try:
        value = float(core)
    except ValueError:
        return None
    mult = _SCALE_MULTIPLIERS.get(suffix.lower(), 1)
    value *= mult
    decimals = len(core.split(".")[1]) if "." in core else 0
    tolerance = 0.5 * (10 ** -decimals) * mult + 1e-9
    return {"raw": token, "kind": "number", "text": core, "value": value,
            "tolerance": tolerance}


def numbers_in_text(text):
    """Extract every number-like token from text."""
    out = []
    for m in NUMBER_RE.finditer(text or ""):
        parsed = _parse_number_token(m.group(0))
        if parsed is not None:
            out.append(parsed)
    return out


def canonical_figure_fields(tool_outputs):
    """Map canonical case-page fields to values from tool outputs."""
    found = []

    def add(field, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if value == 0:
            return
        entry = (field, abs(value))
        if entry not in found:
            found.append(entry)

    def walk(node, context=""):
        if isinstance(node, dict):
            if node.get("denominator_label") == "Consolidated Interest Expense":
                add("interest_expense", node.get("denominator_value"))
            if node.get("name") == "Interest expense":
                add("interest_expense", node.get("value"))
            for key, value in node.items():
                if key == "numerator" and context != "cure":
                    add("total_debt", value)
                elif key == "ebitdar":
                    add("ebitdar", value)
                elif key == "ebitda":
                    add("ebitda", value)
                elif key == "disallowed":
                    add("disallowed", value)
                elif key == "debt_reduction_needed":
                    add("cure.debt_reduction",
                        value.get("value") if isinstance(value, dict)
                        else value)
                elif key == "ebitda_increase_needed":
                    amount = (value.get("value") if isinstance(value, dict)
                              else value)
                    if context == "interest_coverage":
                        add("cure.interest_ebitda_increase", amount)
                    else:
                        add("cure.ebitda_increase", amount)
                walk(value, key if key in (
                    "net_leverage", "interest_coverage") else context)
        elif isinstance(node, list):
            for item in node:
                walk(item, context)

    walk(tool_outputs or [])
    return found


def verify_memo_numbers(draft, tool_outputs):
    """Check every number in the draft against prior tool outputs.

    A draft number passes when its digits appear verbatim (after stripping
    $, commas, %, and x), when it is a year from a tool-output date, or
    when it equals a tool-output value within rounding tolerance (so
    "$267.2M" matches $267,190,000 and "6.58" matches 6.57636...).
    Returns counts plus the list of unverified (likely invented) numbers.
    """
    corpus_text = json.dumps(tool_outputs or [], default=str)
    corpus_nums = numbers_in_text(corpus_text)
    corpus_dates = {n["text"] for n in corpus_nums if n["kind"] == "date"}
    corpus_years = {d[:4] for d in corpus_dates}
    corpus_texts = {n["text"] for n in corpus_nums if n["kind"] == "number"}
    corpus_values = [n["value"] for n in corpus_nums
                     if n["value"] is not None]
    draft_nums = numbers_in_text(draft)
    canonical = canonical_figure_fields(tool_outputs)
    unverified = []
    figure_fields = []
    for n in draft_nums:
        if n["kind"] == "date":
            ok = n["text"] in corpus_dates
        elif re.fullmatch(r"\d{4}", n["text"]) and n["text"] in corpus_years:
            ok = True
        elif n["text"] in corpus_texts:
            ok = True
        else:
            ok = any(abs(n["value"] - v) <= n["tolerance"]
                     for v in corpus_values)
        if ok and n["value"] is not None:
            for field, value in canonical:
                if abs(abs(n["value"]) - value) <= n["tolerance"]:
                    entry = {"raw": n["raw"].strip(), "field": field,
                             "value": n["value"]}
                    if entry not in figure_fields:
                        figure_fields.append(entry)
                    break
        if not ok:
            raw = n["raw"].strip()
            if raw not in unverified:
                unverified.append(raw)
    if unverified:
        note = ("%d of %d numbers not found in tool outputs; "
                "remove or correct them" % (len(unverified), len(draft_nums)))
    else:
        note = ("all %d numbers appear in tool outputs"
                % len(draft_nums))
    return {"numbers_checked": len(draft_nums),
            "unverified_numbers": unverified,
            "figure_fields": figure_fields,
            "verified": not unverified,
            "note": note}


ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth",
            "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth",
            "thirteenth", "fourteenth", "fifteenth", "sixteenth",
            "seventeenth", "eighteenth", "nineteenth", "twentieth")

_ORDINAL_WORD_RE = re.compile(
    r"\b(" + "|".join(ORDINALS) + r")\b"
    r"(?:\s+[A-Za-z0-9'’\-]+){0,3}?\s+amendments?\b",
    re.IGNORECASE)
_NUMBERED_AMENDMENT_RES = (
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)\s+amendments?\b",
               re.IGNORECASE),
    re.compile(r"\bamendments?\s+(?:no\.?|number|#)?\s*\d{1,2}\b",
               re.IGNORECASE),
)
_QUOTED_TITLE_RE = re.compile(r'"([^"]{3,120})"')
_CAPS_TITLE_RE = re.compile(
    r"\b([A-Z][A-Z0-9&\-']*(?:\s+[A-Z][A-Z0-9&\-']+)+)\b")
_CAPITALIZED_TITLE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9']*(?:\s+[A-Za-z][A-Za-z0-9']*){0,4}?"
    r"\s+(?:Amendment|Agreement|Forbearance))\b")
_TITLE_KEYWORDS = ("agreement", "amendment", "forbearance")


def _title_like(text):
    return any(k in text.lower() for k in _TITLE_KEYWORDS)


def amendment_ordinals_in_text(text):
    """Amendment ordinals named in prose ("thirteenth amendment", "No. 14")."""
    out = []
    for rx in (_ORDINAL_WORD_RE,) + _NUMBERED_AMENDMENT_RES:
        for m in rx.finditer(text or ""):
            cand = re.sub(r"\s+", " ", m.group(0)).strip()
            if cand and cand not in out:
                out.append(cand)
    return out


def document_titles_in_text(text):
    """Document-title candidates in prose: quoted, ALL-CAPS, or Capitalized."""
    out = []

    def _add(cand):
        cand = re.sub(r"\s+", " ", (cand or "")).strip(" :;,-")
        if cand and _title_like(cand) and cand not in out:
            out.append(cand)

    for m in _QUOTED_TITLE_RE.finditer(text or ""):
        _add(m.group(1))
    for m in _CAPS_TITLE_RE.finditer(text or ""):
        _add(m.group(1))
    for m in _CAPITALIZED_TITLE_RE.finditer(text or ""):
        _add(m.group(1))
    return out


def verify_memo_labels(draft, tool_outputs):
    """Check amendment ordinals and document titles against tool outputs.

    Every ordinal naming an amendment (first ... twentieth, plus numbered
    forms like "13th amendment" or "Amendment No. 14") and every
    document-title candidate must appear verbatim (case-insensitive) in
    prior tool outputs; anything else was named by the model and is
    flagged.
    """
    corpus = json.dumps(tool_outputs or [], default=str).lower()
    unverified_ordinals = [o for o in amendment_ordinals_in_text(draft)
                           if o.lower() not in corpus]
    unverified_titles = [t for t in document_titles_in_text(draft)
                         if t.lower() not in corpus]
    return {"unverified_ordinals": unverified_ordinals,
            "unverified_titles": unverified_titles}


def _memo_sentences(text):
    """Split memo prose into sentences without splitting decimals."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text or "")
    return [p.strip() for p in parts if p.strip()]


def verify_memo_drivers(draft):
    """Flag covenant driver sentences that pair the wrong fields."""
    errors = []
    for sentence in _memo_sentences(draft):
        low = sentence.lower()
        if "interest coverage" in low:
            wrong_pair = (
                re.search(r"\bebitdar\b.{0,120}?\b(?:against|over|/)\s+"
                          r"(?:consolidated\s+)?interest\b", low)
                or re.search(r"\bebitdar\b.{0,80}?\binterest\s+expense\b"
                             r".{0,80}?\binterest coverage\b", low)
                or ("ebitdar" in low and "interest of" in low
                    and "interest coverage" in low)
            )
            if wrong_pair:
                errors.append(
                    "interest coverage must use Consolidated EBITDA over "
                    "Consolidated Interest Expense, not Consolidated EBITDAR")
        if "net leverage" in low:
            wrong_pair = re.search(
                r"total debt including operating leases.{0,120}?"
                r"\b(?:against|over|/)\s+consolidated ebitda(?!r)\b", low)
            if wrong_pair:
                errors.append(
                    "net leverage must use total debt including operating "
                    "leases over Consolidated EBITDAR")
    return errors


def repeated_phrases_in_memo(draft, min_words=6):
    """Return 6+ word phrases repeated inside a single memo sentence."""
    repeated = []
    for sentence in _memo_sentences(draft):
        words = re.findall(r"[a-z0-9$%.]+", sentence.lower())
        seen = {}
        for i in range(0, len(words) - min_words + 1):
            phrase = " ".join(words[i:i + min_words])
            if phrase in seen and phrase not in repeated:
                repeated.append(phrase)
            seen[phrase] = i
    return repeated


def verify_memo_format(draft):
    """Flag memo formatting that violates the house style."""
    errors = []
    low_draft = (draft or "").lower()
    if "\u2014" in draft or "\u2013" in draft:
        errors.append("memo contains an em dash or en dash")
    for match in re.finditer(r"\b\d+(?:\.(\d+))?x\b", draft or ""):
        decimals = match.group(1) or ""
        if len(decimals) != 2:
            errors.append(f"ratio {match.group(0)} must have two decimals")
    if re.search(r"\b(?:HIGH|MEDIUM|LOW)\s+risk\b", draft or ""):
        errors.append("risk must be lowercase, such as high risk")
    if re.search(r"\baddbacks?\b|\badd backs?\b", draft or "",
                 re.IGNORECASE):
        errors.append("use add-backs, hyphenated")
    if "provides no equity cure" in low_draft or (
            "no equity cure available" in low_draft):
        errors.append(
            "write: No equity cure provision was found in the reviewed "
            "agreement")
    if re.search(r"\b\d{4} fails\b", draft or ""):
        errors.append("after a test date, write failures, not fails")
    raw_phrases = (
        "not available (no company leverage table disclosed)",
        "sensitivity without lender-approved projected savings",
        "without lender-approved projected savings",
        "consolidated adjusted ebitda forecast",
        "lesser of consolidated adjusted ebitda",
        "public filings",
    )
    for phrase in raw_phrases:
        if phrase in low_draft:
            errors.append(f"rewrite the raw tool wording: {phrase}")
    if re.search(r"requires agent approval", low_draft):
        errors.append("say requires administrative agent approval")
    prose = "\n".join(
        line for line in (draft or "").splitlines()
        if not line.lstrip().startswith("|"))
    for name in ("Net Leverage Ratio", "Interest Coverage Ratio",
                 "Net Leverage", "Interest Coverage"):
        if re.search(rf"\b{name}\b", prose):
            errors.append(
                f"covenant name {name} must be sentence case in prose")
            break
    return errors


# ---------------------------------------------------------------------------
# Company lookup (registry, SEC ticker list, EDGAR name search)
# ---------------------------------------------------------------------------

BROWSE_EDGAR_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?company={query}"
                    "&type=10-K&dateb=&owner=include&count=10&action=getcompany")
TICKERS_URL_FALLBACK = "https://www.sec.gov/files/company_tickers.json"


def _parse_browse_edgar_html(html):
    """Parse EDGAR company search HTML into [{cik, cik10, name}].

    Handles both the single-company page (span.companyName with a CIK
    link) and the multi-company table (table.tableFile2 with CIK/Company
    columns). Every row is kept, including delisted/inactive companies.
    """
    results = []
    seen = set()

    def _add(cik_raw, name):
        digits = _cik_digits(cik_raw)
        if not digits:
            return
        plain = str(int(digits))
        if plain in seen:
            return
        seen.add(plain)
        clean = re.sub(r"\s+", " ", str(name or "").strip())
        if not clean:
            return
        results.append({"cik": plain, "cik10": _cik10(digits),
                        "name": clean})

    text = html or ""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        BeautifulSoup = None
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(text, "html.parser")
        except Exception:
            soup = None
        if soup is not None:
            for span in soup.find_all("span", class_="companyName"):
                full = span.get_text(" ", strip=True)
                cik = None
                link = span.find("a", href=True)
                if link:
                    href = link.get("href") or ""
                    m = re.search(r"CIK=0*(\d+)", href, re.IGNORECASE)
                    if m:
                        cik = m.group(1)
                    if not cik:
                        m = re.search(r"(\d{6,10})",
                                      link.get_text(strip=True))
                        if m:
                            cik = m.group(1)
                if not cik:
                    m = re.search(r"CIK\s*#?\s*:?\s*(\d+)", full,
                                  re.IGNORECASE)
                    if m:
                        cik = m.group(1)
                name = re.split(r"\bCIK\b", full,
                                flags=re.IGNORECASE)[0].strip(" #:-\u2013\u2014")
                if cik:
                    _add(cik, name)
            for table in soup.find_all("table", class_="tableFile2"):
                header = table.find("tr")
                if header is not None:
                    htext = header.get_text(" ", strip=True).lower()
                    if ("filing" in htext or "format" in htext
                            or "description" in htext):
                        continue
                    if "cik" not in htext or "company" not in htext:
                        continue
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all(["td", "th"])
                    if len(cells) < 2:
                        continue
                    cik = None
                    m = re.search(r"(\d+)",
                                  cells[0].get_text(strip=True))
                    if m:
                        cik = m.group(1)
                    if not cik:
                        link = cells[0].find("a", href=True)
                        if link:
                            m = re.search(r"CIK=0*(\d+)",
                                          link.get("href") or "",
                                          re.IGNORECASE)
                            if m:
                                cik = m.group(1)
                    name = ""
                    for piece in cells[1].stripped_strings:
                        name = piece.strip()
                        break
                    if not name:
                        name = re.split(
                            r"\bSIC\b",
                            cells[1].get_text(" ", strip=True),
                            flags=re.IGNORECASE)[0].strip()
                    if cik:
                        _add(cik, name)
            if results:
                return results
    for m in re.finditer(
            r"CIK=0*(\d+)[^>]*>\s*0*(\d+)\s*</a>\s*</td>\s*"
            r"<td[^>]*>\s*([^<]+?)\s*<br",
            text, re.IGNORECASE | re.DOTALL):
        _add(m.group(1), m.group(3))
    for m in re.finditer(
            r'class="companyName"[^>]*>\s*([^<]+?)\s*<acronym[^>]*>CIK'
            r"</acronym>\s*#?:?\s*<a[^>]*CIK=0*(\d+)",
            text, re.IGNORECASE | re.DOTALL):
        _add(m.group(2), m.group(1))
    return results


def _lookup_ticker_list(query):
    """Match query against the SEC ticker list; returns [(ticker, title, cik)]."""
    import edgar

    tickers_url = getattr(edgar, "TICKERS_URL", TICKERS_URL_FALLBACK)
    path = edgar.fetch(tickers_url, "company_tickers.json")
    data = json.loads(Path(path).read_text(encoding="utf-8",
                                           errors="replace"))
    entries = data.values() if isinstance(data, dict) else data
    q = str(query or "").strip()
    qu, ql = q.upper(), q.lower()
    q_plain = _cik_plain(q) if q.isdigit() else None
    exact, titles, cik_hit, partial = [], [], [], []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip()
        title = str(entry.get("title") or "").strip()
        plain = _cik_plain(entry.get("cik_str", ""))
        if not plain:
            continue
        if q_plain and plain == q_plain:
            cik_hit.append((ticker, title, plain))
        if ticker.upper() == qu:
            exact.append((ticker, title, plain))
        elif title.lower() == ql:
            titles.append((ticker, title, plain))
        elif ql and ql in title.lower():
            partial.append((ticker, title, plain))
    if q_plain and cik_hit:
        return cik_hit
    if exact:
        return exact
    if titles:
        return titles
    return partial[:10]


def _browse_edgar_search(name):
    """Run the EDGAR company-name search through edgar.fetch (cached)."""
    import edgar
    from urllib.parse import quote_plus

    q = str(name or "").strip()
    url = BROWSE_EDGAR_URL.format(query=quote_plus(q))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", q)[:60].strip("_") or "company"
    path = edgar.fetch(url, f"browse_{slug}.htm")
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    return _parse_browse_edgar_html(html)


def _candidate(cik_plain, name, source, ticker=None):
    # NOTE: the registry "status" field (e.g. "delisted 2026 (Chapter 11)")
    # is deliberately never returned: it can postdate as_of, so it stays
    # internal and out of the model's tool outputs.
    cand = {"cik": cik_plain, "cik10": _cik10(cik_plain),
            "name": name, "source": source,
            "found_via": source, "how": source}
    if ticker:
        cand["ticker"] = ticker
    return cand


def tool_lookup_company(name_or_ticker="", company=None, as_of=None,
                        **kwargs):
    """Resolve a company name or ticker to CIK candidates (delisted OK).

    Order: local data/companies.json registry, SEC ticker list, EDGAR
    company-name search. Returns {"query", "as_of",
    "candidates": [{cik, name, source, ...}]}; each candidate records
    how it was found. The registry "status" field is kept internal so
    no post-as_of fact leaks to the model.
    """
    query = (str(name_or_ticker or "").strip()
             or str(company or "").strip()
             or str(kwargs.get("ticker") or "").strip()
             or str(kwargs.get("name") or "").strip()
             or str(kwargs.get("query") or "").strip())
    if not query:
        return _record({"query": name_or_ticker,
                        "candidates": [],
                        "as_of": as_of,
                        "error": "empty company query"})
    registry = _load_companies_registry()
    qu, ql = query.upper(), query.lower()
    q_plain = _cik_plain(query) if query.isdigit() else None
    reg_hits = []
    for key, info in registry.items():
        if not isinstance(info, dict):
            continue
        plain = _cik_plain(info.get("cik"))
        if not plain:
            continue
        name = str(info.get("name") or key)
        ticker = str(key)
        if q_plain:
            matched = plain == q_plain
        elif ticker.upper() == qu:
            matched = True
        else:
            nl = name.lower()
            matched = ql == nl or ql in nl or nl in ql
        if matched:
            reg_hits.append(_candidate(plain, name, "registry",
                                       ticker=ticker))
    if reg_hits:
        reg_hits.sort(key=lambda c: 0
                      if str(c.get("ticker", "")).upper() == qu else 1)
        return _record({"query": query, "as_of": as_of,
                        "candidates": reg_hits})
    ticker_error = None
    try:
        ticker_hits = _lookup_ticker_list(query)
    except Exception as exc:
        ticker_hits = []
        ticker_error = f"{type(exc).__name__}: {exc}"
    if ticker_hits:
        return _record({
            "query": query, "as_of": as_of,
            "candidates": [_candidate(plain, title, "ticker_list",
                                      ticker=ticker)
                           for ticker, title, plain in ticker_hits],
        })
    if q_plain:
        return _record({"query": query, "as_of": as_of,
                        "candidates": [_candidate(q_plain, query, "cik")]})
    try:
        parsed = _browse_edgar_search(query)
    except Exception as exc:
        detail = f"ticker list: {ticker_error or 'no match'}; EDGAR search failed: {exc}"
        return _record({"query": query, "as_of": as_of, "candidates": [],
                        "error": f"no CIK found for {query!r} ({detail})"})
    if parsed:
        return _record({
            "query": query, "as_of": as_of,
            "candidates": [_candidate(p["cik"], p["name"], "edgar_search")
                           for p in parsed],
        })
    return _record({"query": query, "as_of": as_of, "candidates": [],
                    "error": f"no CIK found for {query!r}"})


# ---------------------------------------------------------------------------
# Tools (thin wrappers over the existing modules; compact JSON only)
# ---------------------------------------------------------------------------

def _compact_candidate(cand):
    """Pick metadata fields from an EDGAR candidate (never document text)."""
    n = cand.get("char_count", cand.get("character_count", 0))
    return {
        "url": cand.get("url"),
        "filingDate": cand.get("filingDate"),
        "form": cand.get("form"),
        "description": cand.get("description"),
        "title": cand.get("title"),
        "is_forbearance": bool(cand.get("is_forbearance")),
        "is_amendment": bool(cand.get("is_amendment")),
        "is_complete": bool(cand.get("is_complete")),
        "char_count": n,
    }


def _call_with_timeout(func, timeout, label):
    """Run func in a worker thread, raising TimeoutError after `timeout`s."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        executor.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(
            f"{label} timed out after {timeout} seconds") from None
    finally:
        executor.shutdown(wait=False)


def _discovery_cache_present(ticker):
    """True when EDGAR discovery inputs for this ticker are already cached.

    Discovery is cached under data/raw by edgar.fetch (the submissions
    index plus filing index pages and exhibits), so a present submissions
    file means select_agreement reuses those files instead of fetching.
    """
    cik10 = ""
    tok = str(ticker or "").strip()
    if tok.isdigit():
        cik10 = tok.zfill(10)[-10:]
    else:
        for key, info in _load_companies_registry().items():
            if not isinstance(info, dict):
                continue
            if str(key).upper() == tok.upper() and info.get("cik"):
                cik10 = _cik10(info["cik"])
                break
    if not cik10:
        return False
    return (DATA_DIR / "raw" / f"submissions_CIK{cik10}.json").exists()


def governing_doc_type(base, amendments=None):
    """Classify the governing document as forbearance, amendment, or base."""
    base = base or {}
    title = str(base.get("title") or "").lower()
    description = str(base.get("description") or "").lower()
    if (base.get("is_forbearance") or "forbearance" in title
            or "forbearance" in description):
        return "forbearance"
    if (base.get("is_amendment") or "amendment" in title
            or "amendment" in description):
        return "amendment"
    return "base"


def tool_find_agreements(company, as_of=None):
    """select_agreement results: base agreement + amendments (metadata only).

    Filings dated after as_of are excluded by select_agreement. EDGAR
    discovery progress lines are suppressed here; they print only in the
    CLI discover/select commands. Cached discovery data under data/raw
    is reused when present (edgar.fetch returns cached files without a
    network fetch). The call is bounded by TOOL_TIMEOUT_SECONDS via
    dispatch_tool; a timeout becomes an error result the UI can show.
    """
    import edgar

    ticker = resolve_ticker(company)
    cached = _discovery_cache_present(ticker)
    # verbose=False keeps discovery quiet; stdout is never redirected
    # here because this runs in a worker thread and redirect_stdout is
    # process-wide.
    base, amendments = edgar.select_agreement(
        ticker, as_of=as_of, verbose=False)
    return _record({
        "company": company,
        "ticker": ticker,
        "as_of": as_of,
        "cached_discovery": cached,
        "governing_doc_type": governing_doc_type(base, amendments),
        "base": _compact_candidate(base) if base is not None else None,
        "amendments": [_compact_candidate(c) for c in (amendments or [])],
    })


def summarize_extraction(data):
    """Compact covenant summary: thresholds, cap groups, definition terms."""
    covenants = []
    for c in data.get("financial_covenants", []) or []:
        covenants.append({
            "id": c.get("id"), "name": c.get("name"),
            "section": c.get("section"), "direction": c.get("direction"),
            "metric_term": c.get("metric_term"), "unit": c.get("unit"),
            "thresholds": c.get("thresholds", []),
        })
    caps = []
    for g in data.get("cap_groups", []) or []:
        caps.append({
            "id": g.get("id"),
            "applies_to_clauses": g.get("applies_to_clauses", []),
            "schedule": g.get("schedule", []),
        })
    terms = sorted({d.get("term") for d in data.get("definitions", []) or []
                    if d.get("term")})
    field = data.get("equity_cure")
    if isinstance(field, dict):
        equity_cure = {"present": field.get("present"),
                       "section": field.get("section"),
                       "max_uses": field.get("max_uses"),
                       "limits": field.get("limits"),
                       "how_applied": field.get("how_applied")}
    else:
        equity_cure = None
    return {"borrower": data.get("borrower"),
            "agreement": data.get("agreement"),
            "financial_covenants": covenants,
            "cap_groups": caps,
            "definition_terms": terms,
            "equity_cure": equity_cure}


def tool_extract_covenants(company, agreement_url, as_of=None,
                         client=None, max_tokens=None):
    """Download + textify + LLM-extract + quote-verify a credit agreement.

    When a reviewed extraction already exists for the company, it is
    returned instead (and the note says so) without any model call.
    As-of discipline flows through agreement selection: the caller
    passes the agreement found under as_of, and as_of is echoed here.
    """
    slug = company_slug(company)
    reviewed_path = DATA_DIR / "extracted" / f"{slug}_covenants.reviewed.json"
    if reviewed_path.exists():
        data = json.loads(reviewed_path.read_text(encoding="utf-8"))
        return _record({
            "reviewed": True,
            "company": company,
            "as_of": as_of,
            "note": ("A reviewed extraction already exists for %s at %s; "
                     "returning it instead of re-extracting."
                     % (company, reviewed_path)),
            "verified": None,
            "total": None,
            "saved_path": str(reviewed_path),
            **summarize_extraction(data),
        })

    import edgar
    import extract as extract_mod

    raw_name = (agreement_url or "").rstrip("/").split("/")[-1] or "agreement"
    raw_name = re.sub(r"[^A-Za-z0-9._-]", "_", raw_name)
    filename = f"{slug}_{raw_name}"
    if not filename.endswith((".htm", ".html")):
        filename += ".htm"
    dest = edgar.fetch(agreement_url, filename)
    document = textify.html_to_text(Path(dest).read_bytes())
    content = document + "\n\n---\n\n" + extract_mod.INSTRUCTIONS
    if client is None:
        client = build_client()

    def request():
        return client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens or extract_mod.MAX_TOKENS,
            temperature=0,
        )

    response = request()
    raw = response.choices[0].message.content or ""
    try:
        parsed = json.loads(extract_mod.strip_code_fences(raw))
    except json.JSONDecodeError:
        response = request()  # retry once
        raw = response.choices[0].message.content or ""
        parsed = json.loads(extract_mod.strip_code_fences(raw))

    out_dir = DATA_DIR / "extracted"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{slug}_covenants.json"
    raw_path = out_dir / f"{slug}_raw_response.txt"
    raw_path.write_text(raw, encoding="utf-8")
    json_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")

    quotes = []
    extract_mod.collect_quotes(parsed, quotes)
    source_norm = extract_mod.normalize(document)
    verified = 0
    for q in quotes:
        if extract_mod.normalize(q) and extract_mod.normalize(q) in source_norm:
            verified += 1
    return _record({
        "reviewed": False,
        "company": company,
        "agreement_url": agreement_url,
        "as_of": as_of,
        "verified": verified,
        "total": len(quotes),
        "saved_path": str(json_path),
        **summarize_extraction(parsed),
    })


def _after_as_of_error(company, period, as_of, key):
    return {
        "supported": True,
        "company": company,
        key: period,
        "as_of": as_of,
        "error": (f"{key} {period} is after as_of {as_of}; refusing to use "
                  "information dated after as_of"),
    }


def _unsupported(company, period, tool):
    return {
        "supported": False,
        "company": company,
        "period_end" if tool == "compute" else "base_period": period,
        "reason": ("Covenant %s is currently supported for SNBR only; "
                   "no result pipeline exists for %r, so this request is "
                   "unsupported. Do not guess."
                   % ({"compute": "computation",
                       "project": "projection",
                       "cure": "cure analysis"}[tool], company)),
    }


def _compact_verdict(block):
    block = block or {}
    return {"ratio": block.get("ratio"), "ratio_2dp": block.get("ratio_2dp"),
            "threshold": block.get("threshold"),
            "headroom": block.get("headroom"),
            "headroom_2dp": block.get("headroom_2dp"),
            "pass": block.get("pass"), "note": block.get("note"),
            "numerator_label": block.get("numerator_label"),
            "numerator_value": block.get("numerator_value"),
            "denominator_label": block.get("denominator_label"),
            "denominator_value": block.get("denominator_value")}


COVENANT_LABELS = {
    "numerator": "total debt including operating lease liabilities",
    "funded_indebtedness": "funded indebtedness",
    "ebitda": "Consolidated EBITDA",
    "ebitdar": "Consolidated EBITDAR",
}


def tool_compute_covenants(company, period_end, as_of=None):
    """covenant.py result summary (SNBR only; never fabricate).

    Rejects a period_end dated after as_of so no post-cutoff release or
    XBRL data leaks in. Returns explicit figure labels plus a
    reconciliation entry that is "not available (no company leverage
    table disclosed)" when the period has no company reconciliation.
    """
    if company_slug(company) not in SUPPORTED_PIPELINES:
        return _record(_unsupported(company, period_end, "compute"))
    if _period_after_as_of(period_end, as_of):
        return _record(_after_as_of_error(company, period_end, as_of,
                                          "period_end"))
    try:
        result = covenant.compute(period_end)
    except Exception as exc:  # missing data: report, never invent
        return _record({"supported": True, "company": company,
                        "period_end": period_end, "as_of": as_of,
                        "error": f"{type(exc).__name__}: {exc}"})
    try:
        saved = str(covenant.save_result(result))
    except OSError as exc:
        saved = f"save failed: {exc}"
    rec = result.get("reconciliation")
    if rec is not None:
        rec = {"company_ebitda": rec.get("company_ebitda"),
               "onya_ebitda": rec.get("onya_ebitda"),
               "difference": rec.get("difference"),
               "status": rec.get("status"), "note": rec.get("note"),
               "net_leverage_company_ratio_2dp":
                   (rec.get("net_leverage") or {}).get("company_reported", {}).get("ratio_2dp"),
               "net_leverage_company_pass":
                   (rec.get("net_leverage") or {}).get("company_reported", {}).get("pass"),
               "net_leverage_onya_strict_ratio_2dp":
                   (rec.get("net_leverage") or {}).get("onya_strict", {}).get("ratio_2dp"),
               "net_leverage_onya_strict_pass":
                   (rec.get("net_leverage") or {}).get("onya_strict", {}).get("pass")}
    scenarios = []
    for sc in result.get("proforma_scenarios") or []:
        scenarios.append({
            "savings": sc.get("savings"), "ebitda": sc.get("ebitda"),
            "ebitdar": sc.get("ebitdar"),
            "net_leverage": _compact_verdict(sc.get("net_leverage")),
            "interest_coverage": _compact_verdict(sc.get("interest_coverage")),
            "note": sc.get("note"),
        })
    sens = result.get("sensitivity_without_proforma")
    if sens is not None:
        sens = {"ebitda": sens.get("ebitda"), "ebitdar": sens.get("ebitdar"),
                "net_leverage": _compact_verdict(sens.get("net_leverage")),
                "interest_coverage": _compact_verdict(
                    sens.get("interest_coverage")),
                "note": sens.get("note")}
    return _record({
        "supported": True, "company": company, "period_end": period_end,
        "as_of": as_of,
        "units": result.get("units", "USD"),
        "numerator": result.get("numerator"),
        "numerator_thousands": result.get("numerator_thousands"),
        "ebitda": result.get("ebitda"),
        "ebitda_thousands": result.get("ebitda_thousands"),
        "ebitdar": result.get("ebitdar"),
        "ebitdar_thousands": result.get("ebitdar_thousands"),
        "disallowed": result.get("disallowed"),
        "labels": dict(COVENANT_LABELS),
        "net_leverage": _compact_verdict(result.get("net_leverage")),
        "interest_coverage": _compact_verdict(result.get("interest_coverage")),
        "flags": {
            "data_quality_warnings": result.get("data_quality_warnings", []),
            "warning_count": len(result.get("data_quality_warnings", []) or []),
            "reconciliation": (rec if rec is not None
                               else RECONCILIATION_UNAVAILABLE),
            "unverifiable_proforma": bool(result.get("proforma_scenarios")),
        },
        "scenarios": scenarios,
        "sensitivity_without_proforma": sens,
        "saved_path": saved,
    })


def tool_project_next_test(company, base_period, as_of=None):
    """project.py summary: next test, ratios, cushions, risk, backtest.

    Rejects a base_period dated after as_of.
    """
    if company_slug(company) not in SUPPORTED_PIPELINES:
        return _record(_unsupported(company, base_period, "project"))
    if _period_after_as_of(base_period, as_of):
        return _record(_after_as_of_error(company, base_period, as_of,
                                          "base_period"))
    try:
        result = project.compute(base_period)
    except Exception as exc:
        return _record({"supported": True, "company": company,
                        "base_period": base_period, "as_of": as_of,
                        "error": f"{type(exc).__name__}: {exc}"})
    try:
        saved = str(project.save_result(result))
    except OSError as exc:
        saved = f"save failed: {exc}"
    projections = {}
    for basis in ("onya", "company"):
        p = (result.get("projections") or {}).get(basis) or {}
        projections[basis] = {"ebitda": p.get("ebitda"),
                              "ebitdar": p.get("ebitdar"),
                              "ratio": p.get("ratio"),
                              "ratio_2dp": p.get("ratio_2dp"),
                              "threshold": p.get("threshold"),
                              "pass": p.get("pass")}
    back = result.get("backtest")
    if back is not None:
        like = back.get("like_for_like") or {}
        like_lev = like.get("net_leverage") or {}
        back = {"period_end": back.get("period_end"),
                "numerator": back.get("numerator"),
                "matched_savings": back.get("matched_savings"),
                "like_for_like_ratio_2dp": like_lev.get("ratio_2dp"),
                "like_for_like_pass": like_lev.get("pass"),
                "file_proforma": back.get("file_proforma")}
    trend = result.get("trend") or {}
    return _record({
        "supported": True, "company": company, "base_period": base_period,
        "as_of": as_of,
        "next_test": result.get("next_test"),
        "next_threshold": result.get("next_threshold"),
        "threshold_note": result.get("threshold_note"),
        "ix_cap": result.get("ix_cap"), "ix_note": result.get("ix_note"),
        "iv_viii_cap": result.get("iv_viii_cap"),
        "projected_proforma": result.get("projected_proforma"),
        "projections": projections,
        "cushion": result.get("cushion"),
        "quarters_of_cushion": result.get("quarters_of_cushion"),
        "risk": result.get("risk"), "risk_rule": result.get("risk_rule"),
        "trend_label": trend.get("label", project.TREND_LABEL),
        "trend_avg_decline": trend.get("avg_decline"),
        "avg_quarterly_change": trend.get("avg_quarterly_change"),
        "trend_series": trend.get("series", []),
        "backtest": back,
        "saved_path": saved,
    })


def _compact_cure_block(block):
    block = block or {}
    figures = {}
    for name, fig in (block.get("figures") or {}).items():
        figures[name] = (fig or {}).get("value")
    return {"status": block.get("status"), "figures": figures,
            "summary": block.get("summary")}


def tool_cure_analysis(company, period_end, as_of=None):
    """cure.py summaries: dollar cures per covenant plus equity-cure status.

    Rejects a period_end dated after as_of.
    """
    if company_slug(company) not in SUPPORTED_PIPELINES:
        return _record(_unsupported(company, period_end, "cure"))
    if _period_after_as_of(period_end, as_of):
        return _record(_after_as_of_error(company, period_end, as_of,
                                          "period_end"))
    try:
        result = cure.compute(period_end)
    except Exception as exc:
        return _record({"supported": True, "company": company,
                        "period_end": period_end, "as_of": as_of,
                        "error": f"{type(exc).__name__}: {exc}"})
    try:
        saved = str(cure.save_result(period_end, result))
    except OSError as exc:
        saved = f"save failed: {exc}"
    scenarios = []
    for sc in result.get("proforma_scenarios") or []:
        scenarios.append({
            "savings": sc.get("savings"),
            "net_leverage": _compact_cure_block(sc.get("net_leverage")),
            "interest_coverage": _compact_cure_block(
                sc.get("interest_coverage")),
        })
    eq = result.get("equity_cure") or {}
    return _record({
        "supported": True, "company": company, "period_end": period_end,
        "as_of": as_of,
        "units": result.get("units", "USD"),
        "interest": (result.get("interest") or {}).get("value"),
        "base": {
            "net_leverage": _compact_cure_block(
                (result.get("base") or {}).get("net_leverage")),
            "interest_coverage": _compact_cure_block(
                (result.get("base") or {}).get("interest_coverage")),
        },
        "scenarios": scenarios,
        "equity_cure": {"found": eq.get("found"),
                        "present": eq.get("present"),
                        "section": eq.get("section"),
                        "max_uses": eq.get("max_uses"),
                        "limits": eq.get("limits"),
                        "how_applied": eq.get("how_applied"),
                        "quote": eq.get("quote"),
                        "note": eq.get("note")},
        "saved_path": saved,
    })


def tool_draft_memo(company, period_end, draft="", as_of=None):
    """Verify a model-written watchlist memo: every number, amendment
    ordinal, and document title must come from prior tool outputs.
    Deliberately NOT recorded into the corpus, so a memo can never
    justify its own (or a later memo's) invented numbers."""
    if not (draft or "").strip():
        return {
            "needs_draft": True,
            "company": company,
            "period_end": period_end,
            "as_of": as_of,
            "instruction": ("Call draft_memo again with your full memo prose "
                            "in the 'draft' argument. Write for a credit "
                            "analyst at the lender: lender actions only, never "
                            "advise engaging lenders. Use governing_doc_type: "
                            "when it is forbearance, do not recommend opening "
                            "forbearance or amendment discussions; recommend "
                            "reviewing forbearance terms, termination events, "
                            "and expiry, reserving rights, requesting the "
                            "compliance certificate and add-back support, and "
                            "tightening reporting. Use the headings Summary "
                            "(two sentences), Covenant tests (a small table: "
                            "Covenant, Result, Limit, Headroom, with exact "
                            "figures), What drove it, Cure, Outlook, and "
                            "Recommended actions (three to five bullets). "
                            "Build What drove it only from each covenant's "
                            "numerator and denominator labels and values: "
                            "total debt including operating leases over "
                            "Consolidated EBITDAR for net leverage, and "
                            "Consolidated EBITDA over Consolidated Interest "
                            "Expense for interest coverage. Write scenarios "
                            "once, for example: Net leverage is 5.06x even "
                            "with the maximum $44M of projected savings, and "
                            "6.58x without. Name the avg_quarterly_change "
                            "method in plain words. If cushion is negative, "
                            "state the EBITDAR rise needed to pass the next "
                            "test. When equity_cure.present is false, write "
                            "exactly: No equity cure provision was found in "
                            "the reviewed agreement. After a test date use "
                            "the plural noun failures, never fails. Prose "
                            "style: dates as Apr 4, 2026, ratios "
                            "always two decimals with x, dollars as $267.2 "
                            "million, risk in lowercase, add-backs "
                            "hyphenated, covenant names in sentence case, "
                            "document titles in sentence case, plain words, "
                            "no em dashes. Use only numbers, amendment "
                            "ordinals, and document titles from prior tool "
                            "outputs; every one is verified and any invented "
                            "figure is flagged."),
        }
    report = verify_memo_numbers(draft, _TOOL_OUTPUTS)
    labels = verify_memo_labels(draft, _TOOL_OUTPUTS)
    drivers = verify_memo_drivers(draft)
    repeated = repeated_phrases_in_memo(draft)
    format_errors = verify_memo_format(draft)
    verified = (report["verified"] and not labels["unverified_ordinals"]
                and not labels["unverified_titles"] and not drivers
                and not repeated and not format_errors)
    note = report["note"]
    flagged = labels["unverified_ordinals"] + labels["unverified_titles"]
    if flagged:
        note += ("; %d amendment ordinal(s)/document title(s) not found "
                 "in tool outputs: %s; use only the exact titles and "
                 "labels from tool outputs"
                 % (len(flagged), flagged))
    if drivers:
        note += "; covenant driver errors: " + "; ".join(drivers)
    if repeated:
        note += "; repeated phrases in a sentence: " + "; ".join(repeated)
    if format_errors:
        note += "; formatting errors: " + "; ".join(format_errors)
    return {"memo": draft, "company": company, "period_end": period_end,
            "as_of": as_of,
            "numbers_checked": report["numbers_checked"],
            "unverified_numbers": report["unverified_numbers"],
            "unverified_ordinals": labels["unverified_ordinals"],
            "unverified_titles": labels["unverified_titles"],
            "figure_fields": report["figure_fields"],
            "unverified_drivers": drivers,
            "repeated_phrases": repeated,
            "format_errors": format_errors,
            "verified": verified,
            "note": note}


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function calling) and dispatch
# ---------------------------------------------------------------------------

AS_OF_PARAM = {"type": "string",
               "description": ("Knowledge cutoff (YYYY-MM-DD); information "
                               "dated after this date is ignored")}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "lookup_company",
        "description": ("Resolve a company name or ticker to its CIK, even "
                        "for delisted companies. Checks a local registry, "
                        "then the SEC ticker list, then EDGAR company-name "
                        "search. Returns candidates with cik, name, and "
                        "source."),
        "parameters": {"type": "object", "properties": {
            "name_or_ticker": {"type": "string",
                               "description": "Company name, ticker, or CIK"},
            "as_of": AS_OF_PARAM,
        }, "required": ["name_or_ticker"]},
    }},
    {"type": "function", "function": {
        "name": "find_agreements",
        "description": ("Locate a company's base credit agreement and later "
                        "amendments via EDGAR. Returns compact filing metadata "
                        "(base + amendments), never document text. When the "
                        "user names a test period, pass as_of = period_end + "
                        "45 days (the reporting window)."),
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string",
                        "description": "Company name, ticker, or CIK"},
            "as_of": {"type": "string",
                      "description": ("Only consider filings on/before this "
                                      "date (YYYY-MM-DD); use period_end + "
                                      "45 days when the user names a test "
                                      "period")},
        }, "required": ["company"]},
    }},
    {"type": "function", "function": {
        "name": "extract_covenants",
        "description": ("Download, textify, LLM-extract, and quote-verify a "
                        "credit agreement. Returns thresholds, cap groups, "
                        "definition terms, verified/total counts, and the "
                        "saved path. Prefers an existing reviewed extraction."),
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string",
                        "description": "Company name, ticker, or CIK"},
            "agreement_url": {"type": "string",
                              "description": "SEC URL of the agreement exhibit"},
            "as_of": AS_OF_PARAM,
        }, "required": ["company", "agreement_url"]},
    }},
    {"type": "function", "function": {
        "name": "compute_covenants",
        "description": ("Compute covenant ratios, thresholds, headroom, "
                        "pass/fail, flags, labels, and scenarios for a "
                        "quarterly reporting period. SNBR only; other "
                        "companies return {\"supported\": false}."),
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string",
                        "description": "Company name, ticker, or CIK"},
            "period_end": {"type": "string",
                           "description": "Quarterly reporting period end (YYYY-MM-DD)"},
            "as_of": AS_OF_PARAM,
        }, "required": ["company", "period_end"]},
    }},
    {"type": "function", "function": {
        "name": "project_next_test",
        "description": ("Baseline projection from a base period to the next "
                        "Net Leverage test: projected ratios, cushions, "
                        "trend risk, and backtest. SNBR only."),
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string",
                        "description": "Company name, ticker, or CIK"},
            "base_period": {"type": "string",
                            "description": "Filed base period end (YYYY-MM-DD)"},
            "as_of": AS_OF_PARAM,
        }, "required": ["company", "base_period"]},
    }},
    {"type": "function", "function": {
        "name": "cure_analysis",
        "description": ("Dollar cure figures for each covenant at a filed "
                        "period (debt reduction / EBITDA increase needed, or "
                        "capacity/cushion when passing) plus equity-cure "
                        "status from the reviewed equity_cure field. "
                        "SNBR only."),
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string",
                        "description": "Company name, ticker, or CIK"},
            "period_end": {"type": "string",
                           "description": "Filed period end (YYYY-MM-DD)"},
            "as_of": AS_OF_PARAM,
        }, "required": ["company", "period_end"]},
    }},
    {"type": "function", "function": {
        "name": "draft_memo",
        "description": ("Submit the watchlist memo prose in 'draft'. EVERY "
                        "number, amendment ordinal, and document title in it "
                        "is verified against prior tool outputs; any invented "
                        "figure is flagged in 'unverified_numbers', "
                        "'unverified_ordinals', or 'unverified_titles'. Call "
                        "before giving a final memo."),
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string",
                        "description": "Company name, ticker, or CIK"},
            "period_end": {"type": "string",
                           "description": "Period the memo covers (YYYY-MM-DD)"},
            "draft": {"type": "string",
                      "description": ("Full memo prose; all numbers, amendment "
                                      "ordinals, and document titles must come "
                                      "from tool results")},
            "as_of": AS_OF_PARAM,
        }, "required": ["company", "period_end", "draft"]},
    }},
]

TOOL_FUNCS = {
    "lookup_company": tool_lookup_company,
    "find_agreements": tool_find_agreements,
    "extract_covenants": tool_extract_covenants,
    "compute_covenants": tool_compute_covenants,
    "project_next_test": tool_project_next_test,
    "cure_analysis": tool_cure_analysis,
    "draft_memo": tool_draft_memo,
}


def dispatch_tool(name, arguments, timeout=TOOL_TIMEOUT_SECONDS):
    """Run one tool by name; unknown tools and crashes become error dicts.

    Each call is bounded by `timeout` seconds (45 by default). A timeout
    returns an error dict, which run_agent records as a tool step so the
    UI can show what happened instead of spinning.
    """
    func = TOOL_FUNCS.get(name)
    if func is None:
        return {"error": f"unknown tool: {name}"}
    try:
        result = _call_with_timeout(
            lambda: func(**(arguments or {})), timeout, name)
    except TimeoutError as exc:
        return {"error": str(exc)}
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return json.loads(json.dumps(result, default=str))


# ---------------------------------------------------------------------------
# Short result summaries for the trace
# ---------------------------------------------------------------------------

def _pass_fail(value):
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "n/a"


def _truncate_at_word(text, max_chars=300):
    """Shorten text at a word boundary with an ASCII ellipsis."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars - 3]
    boundary = cut.rfind(" ")
    if boundary > 0:
        cut = cut[:boundary]
    return cut.rstrip(" ,;:") + "..."


def summarize_result(tool, result, max_chars=300):
    """One-line summary of a tool result for the run trace."""
    result = result or {}
    if result.get("error"):
        text = f"error: {result['error']}"
    elif result.get("supported") is False:
        text = f"unsupported: {result.get('reason', '')}"
    elif tool == "lookup_company":
        cands = result.get("candidates") or []
        if cands:
            first = cands[0]
            text = ("%s: %d candidate(s), first %s CIK %s via %s" % (
                result.get("query"), len(cands),
                first.get("name"), first.get("cik"),
                first.get("source")))
        else:
            text = "no CIK candidates found"
    elif tool == "find_agreements":
        base = result.get("base") or {}
        n = len(result.get("amendments") or [])
        if base:
            text = ("base: %s %s %s; %d amendment(s)" % (
                base.get("filingDate"), base.get("form"),
                base.get("title") or "", n))
        else:
            text = "no complete agreement found"
    elif tool == "extract_covenants":
        if result.get("reviewed"):
            text = "reviewed file used: %s" % result.get("saved_path")
        else:
            text = ("%d covenant(s), %d cap group(s), %d definition term(s); "
                    "quotes verified %s/%s; saved %s" % (
                        len(result.get("financial_covenants") or []),
                        len(result.get("cap_groups") or []),
                        len(result.get("definition_terms") or []),
                        result.get("verified"), result.get("total"),
                        result.get("saved_path")))
    elif tool == "compute_covenants":
        lev, cov = result.get("net_leverage") or {}, result.get("interest_coverage") or {}
        text = ("%s %s: leverage %s vs %s %s, coverage %s vs %s %s" % (
            result.get("company"), result.get("period_end"),
            lev.get("ratio_2dp"), lev.get("threshold"),
            _pass_fail(lev.get("pass")),
            cov.get("ratio_2dp"), cov.get("threshold"),
            _pass_fail(cov.get("pass"))))
    elif tool == "project_next_test":
        proj = result.get("projections") or {}
        onya = proj.get("onya") or {}
        text = ("%s %s -> next test %s (threshold %s): projected %s %s; "
                "risk %s" % (
                    result.get("company"), result.get("base_period"),
                    result.get("next_test"), result.get("next_threshold"),
                    onya.get("ratio_2dp"), _pass_fail(onya.get("pass")),
                    (result.get("risk") or {}).get("onya")))
    elif tool == "cure_analysis":
        base = result.get("base") or {}
        lev = base.get("net_leverage") or {}
        cov = base.get("interest_coverage") or {}
        text = ("%s %s: leverage %s, coverage %s; equity cure found=%s" % (
            result.get("company"), result.get("period_end"),
            (lev.get("status") or "").upper(),
            (cov.get("status") or "").upper(),
            (result.get("equity_cure") or {}).get("found")))
    elif tool == "draft_memo":
        if result.get("needs_draft"):
            text = "memo draft requested (no prose submitted yet)"
        elif result.get("verified"):
            text = ("memo verified: all %s numbers appear in tool outputs"
                    % result.get("numbers_checked"))
        else:
            text = ("memo FLAGGED, unverified numbers: %s"
                    % (result.get("unverified_numbers") or []))
            flagged_labels = ((result.get("unverified_ordinals") or [])
                              + (result.get("unverified_titles") or []))
            if flagged_labels:
                text += "; unverified labels: %s" % (flagged_labels,)
    else:
        text = json.dumps(result, default=str)
    return _truncate_at_word(text, max_chars)


# ---------------------------------------------------------------------------
# Trace logging (powers the UI's live agent log)
# ---------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def log_step(trace_path, entry):
    """Append one JSON line to the run trace."""
    with open(trace_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _usage_of(response):
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    total = getattr(usage, "total_tokens", 0) or (prompt + completion)
    return {"prompt": prompt, "completion": completion, "total": total}


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

RETRY_FINAL_PROMPT = "Give your final answer now, citing tool results."


def _fallback_answer(user_prompt, history):
    """Non-empty summary built from the trace when the model goes silent."""
    lines = ["I was unable to produce a final answer for your request.",
             "Request: %s" % str(user_prompt or "")[:300]]
    if not history:
        lines.append("What was tried: no tool calls completed before "
                     "the model returned empty content.")
        lines.append("What failed: the model returned empty content twice, "
                     "so there are no tool results to cite.")
        lines.append("Why: empty model output (possibly a model or "
                     "transport issue). Try re-running the request.")
        return "\n".join(lines)
    tried = "; ".join(
        "%s(%s)" % (h.get("tool"),
                    json.dumps(h.get("arguments") or {},
                               default=str)[:150])
        for h in history)
    lines.append("What was tried: %d tool call(s): %s"
                 % (len(history), tried))
    failed = [h for h in history if (h.get("result") or {}).get("error")]
    unsupported = [h for h in history
                   if (h.get("result") or {}).get("supported") is False]
    if failed:
        lines.append("What failed: " + "; ".join(
            "%s: %s" % (h.get("tool"),
                        (h.get("result") or {}).get("error"))
            for h in failed))
    elif unsupported:
        lines.append("What failed: " + "; ".join(
            "%s: unsupported (%s)" % (
                h.get("tool"),
                ((h.get("result") or {}).get("reason") or "")[:200])
            for h in unsupported))
    else:
        lines.append("What failed: the model returned empty content "
                     "despite successful tool results.")
    if failed or unsupported:
        lines.append("Why: tool errors left no citable figures for a final "
                     "answer, and the follow-up prompt also returned empty "
                     "content. Partial findings are in the run trace.")
    else:
        lines.append("Why: the model returned empty content twice. "
                     "Partial tool results are in the run trace.")
    lines.append("Tool summaries: " + " | ".join(
        str(h.get("summary") or "")[:200] for h in history[-5:]))
    return "\n".join(lines)


def run_agent(user_prompt, client=None, run_id=None,
              max_tool_calls=MAX_TOOL_CALLS):
    """Run the tool-calling loop; returns the final answer plus run stats."""
    os.chdir(PROJECT_ROOT)
    reset_corpus()
    run_id = run_id or uuid.uuid4().hex[:12]
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = RUNS_DIR / f"{run_id}.jsonl"
    if client is None:
        client = build_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}]
    log_step(trace_path, {"run_id": run_id, "step": 0,
                          "timestamp": _utcnow(), "type": "run_start",
                          "tool": None, "arguments": {},
                          "result_summary": user_prompt[:300],
                          "tokens": {"prompt": 0, "completion": 0, "total": 0},
                          "total_tokens": 0, "model": MODEL, "tier": TIER})

    total_tokens = 0
    tool_calls = 0
    step = 0
    history = []
    seen_results = {}
    last_figure_fields = []

    def _log_final(content, turn):
        step_nl = step + 1
        log_step(trace_path, {"run_id": run_id, "step": step_nl,
                              "timestamp": _utcnow(),
                              "type": "assistant_final",
                              "tool": None, "arguments": {},
                              "result_summary": content[:300],
                              "tokens": turn,
                              "total_tokens": total_tokens})
        return step_nl

    def budget_exceeded():
        log_step(trace_path, {"run_id": run_id, "step": step,
                              "timestamp": _utcnow(), "type": "run_end",
                              "tool": None, "arguments": {},
                              "result_summary": (
                                  "stopped: run token budget (%d) exceeded"
                                  % TOKEN_BUDGET),
                              "tokens": {"prompt": 0, "completion": 0,
                                         "total": 0},
                              "total_tokens": total_tokens,
                              "reason": "token_budget_exceeded"})
        return {"answer": ("I stopped because this run exceeded its %d-token "
                           "budget. Partial findings are in the run trace."
                           % TOKEN_BUDGET),
                "reason": "token_budget_exceeded", "run_id": run_id,
                "tool_calls": tool_calls, "total_tokens": total_tokens,
                "trace_path": str(trace_path)}

    while True:
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOL_SCHEMAS,
            tool_choice="auto", max_tokens=MAX_TOKENS)
        turn = _usage_of(response)
        total_tokens += turn["total"]
        if total_tokens > TOKEN_BUDGET:
            return budget_exceeded()

        message = response.choices[0].message
        content = message.content or ""
        calls = list(message.tool_calls or [])

        if not calls:
            if not content.strip():
                messages.append({"role": "user",
                                 "content": RETRY_FINAL_PROMPT})
                retry = client.chat.completions.create(
                    model=MODEL, messages=messages, tools=TOOL_SCHEMAS,
                    tool_choice="auto", max_tokens=MAX_TOKENS)
                retry_turn = _usage_of(retry)
                total_tokens += retry_turn["total"]
                if total_tokens > TOKEN_BUDGET:
                    return budget_exceeded()
                retry_msg = retry.choices[0].message
                retry_calls = list(retry_msg.tool_calls or [])
                if retry_calls:
                    content, calls, turn = (retry_msg.content or "",
                                            retry_calls, retry_turn)
                else:
                    retry_content = retry_msg.content or ""
                    if retry_content.strip():
                        step = _log_final(retry_content, retry_turn)
                        log_step(trace_path, {
                            "run_id": run_id, "step": step,
                            "timestamp": _utcnow(), "type": "run_end",
                            "tool": None, "arguments": {},
                            "result_summary": "done",
                            "tokens": {"prompt": 0, "completion": 0,
                                       "total": 0},
                            "total_tokens": total_tokens,
                            "reason": "done"})
                        return {"answer": retry_content, "reason": "done",
                                "run_id": run_id, "tool_calls": tool_calls,
                                "total_tokens": total_tokens,
                                "figure_fields": last_figure_fields,
                                "trace_path": str(trace_path)}
                    fallback = _fallback_answer(user_prompt, history)
                    step = _log_final(fallback, retry_turn)
                    log_step(trace_path, {
                        "run_id": run_id, "step": step,
                        "timestamp": _utcnow(), "type": "run_end",
                        "tool": None, "arguments": {},
                        "result_summary": "done (empty-final fallback)",
                        "tokens": {"prompt": 0, "completion": 0, "total": 0},
                        "total_tokens": total_tokens,
                        "reason": "done"})
                    return {"answer": fallback, "reason": "done",
                            "run_id": run_id, "tool_calls": tool_calls,
                            "total_tokens": total_tokens,
                            "trace_path": str(trace_path)}
            else:
                step = _log_final(content, turn)
                log_step(trace_path, {"run_id": run_id, "step": step,
                                      "timestamp": _utcnow(), "type": "run_end",
                                      "tool": None, "arguments": {},
                                      "result_summary": "done",
                                      "tokens": {"prompt": 0, "completion": 0,
                                                 "total": 0},
                                      "total_tokens": total_tokens,
                                      "reason": "done"})
                return {"answer": content, "reason": "done", "run_id": run_id,
                        "tool_calls": tool_calls, "total_tokens": total_tokens,
                        "figure_fields": last_figure_fields,
                        "trace_path": str(trace_path)}

        messages.append({
            "role": "assistant", "content": content or None,
            "tool_calls": [{"id": c.id, "type": "function",
                            "function": {"name": c.function.name,
                                         "arguments": c.function.arguments}}
                           for c in calls],
        })
        for call in calls:
            name = call.function.name
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except (ValueError, TypeError):
                arguments = {}
                result = {"error": "tool arguments were not valid JSON"}
            else:
                cache_key = (name, json.dumps(arguments, sort_keys=True,
                                              default=str))
                if cache_key in seen_results:
                    # Identical call already made this run: reuse its
                    # result instead of running the tool again.
                    result = json.loads(json.dumps(seen_results[cache_key],
                                                   default=str))
                elif tool_calls >= max_tool_calls:
                    result = {"error": ("tool-call budget exhausted "
                                        "(max %d)" % max_tool_calls)}
                else:
                    result = dispatch_tool(name, arguments)
                    seen_results[cache_key] = result
                    tool_calls += 1
                    if name == "draft_memo" and isinstance(result, dict):
                        last_figure_fields = (
                            result.get("figure_fields") or last_figure_fields)
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, default=str)[:20000]})
            step += 1
            summary = summarize_result(name, result)
            log_step(trace_path, {"run_id": run_id, "step": step,
                                  "timestamp": _utcnow(), "type": "tool_call",
                                  "tool": name, "arguments": arguments,
                                  "result_summary": summary,
                                  "tokens": turn,
                                  "total_tokens": total_tokens})
            history.append({"tool": name, "arguments": arguments,
                            "result": result, "summary": summary})

        if tool_calls >= max_tool_calls:
            messages.append({
                "role": "user",
                "content": ("You have reached the %d tool-call limit. "
                            "Summarize your findings so far for the credit "
                            "analyst, citing only numbers from the tool "
                            "outputs above." % max_tool_calls)})
            response = client.chat.completions.create(
                model=MODEL, messages=messages, max_tokens=MAX_TOKENS)
            turn = _usage_of(response)
            total_tokens += turn["total"]
            if total_tokens > TOKEN_BUDGET:
                return budget_exceeded()
            content = response.choices[0].message.content or ""
            if not content.strip():
                messages.append({"role": "user",
                                 "content": RETRY_FINAL_PROMPT})
                retry = client.chat.completions.create(
                    model=MODEL, messages=messages, max_tokens=MAX_TOKENS)
                retry_turn = _usage_of(retry)
                total_tokens += retry_turn["total"]
                if total_tokens > TOKEN_BUDGET:
                    return budget_exceeded()
                content = retry.choices[0].message.content or ""
                turn = retry_turn
                if not content.strip():
                    content = _fallback_answer(user_prompt, history)
            step = _log_final(content, turn)
            log_step(trace_path, {"run_id": run_id, "step": step,
                                  "timestamp": _utcnow(), "type": "run_end",
                                  "tool": None, "arguments": {},
                                  "result_summary": ("stopped after %d tool "
                                                     "calls" % tool_calls),
                                  "tokens": {"prompt": 0, "completion": 0,
                                             "total": 0},
                                  "total_tokens": total_tokens,
                                  "reason": "max_tool_calls"})
            return {"answer": content, "reason": "max_tool_calls",
                    "run_id": run_id, "tool_calls": tool_calls,
                    "total_tokens": total_tokens,
                    "figure_fields": last_figure_fields,
                    "trace_path": str(trace_path)}


# ---------------------------------------------------------------------------
# Client and CLI
# ---------------------------------------------------------------------------

def build_client():
    """OpenAI SDK client over META_BASE_URL (env from ~/.config/onya/.env)."""
    load_dotenv(os.path.expanduser("~/.config/onya/.env"))
    api_key = os.getenv("META_API_KEY")
    base_url = os.getenv("META_BASE_URL")
    if not api_key:
        raise SystemExit("META_API_KEY missing from ~/.config/onya/.env")
    if not base_url:
        raise SystemExit("META_BASE_URL missing from ~/.config/onya/.env")
    return OpenAI(api_key=api_key, base_url=base_url,
                  timeout=120, max_retries=2)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 2
    outcome = run_agent(argv[1])
    print(outcome["answer"])
    print("\n[run %s: %d tool call(s), %d tokens, trace %s]"
          % (outcome["run_id"], outcome["tool_calls"],
             outcome["total_tokens"], outcome["trace_path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
