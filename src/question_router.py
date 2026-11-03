"""Decides what a question gets, in Python, before any model call.

Sleep Number gets the full check, built from a fixed prompt, so the
visitor's text never reaches the model. Back-tested borrowers, unknown
companies, off-topic questions, and injection attempts are answered here
with no model call and no claim on the limits.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date

import agent

ROUTE_SNBR = "snbr"
ROUTE_BACKTESTED = "backtested"
ROUTE_UNKNOWN = "unknown"
ROUTE_OFF_TOPIC = "off_topic"

COVERED = {
    "AIN": ("Albany International", ("albany international", "albany")),
    "AMCX": ("AMC Networks", ("amc networks", "amc network", "amc")),
    "CRS": ("Carpenter Technology", ("carpenter technology", "carpenter")),
    "GPK": ("Graphic Packaging", ("graphic packaging",)),
    "HAIN": ("Hain Celestial", ("hain celestial", "hain")),
    "NUVR": ("Nuvera Communications", ("nuvera communications", "nuvera")),
    "OPTX": ("Syntec Optics", ("syntec optics", "syntec")),
    "ORLY": ("O'Reilly Automotive", ("o'reilly automotive", "o'reilly",
                                     "oreilly")),
    "QUAD": ("Quad", ("quad/graphics", "quad graphics", "quad")),
    "STGW": ("Stagwell", ("stagwell",)),
    "TRS": ("TriMas", ("trimas",)),
}

_SNBR_RE = re.compile(r"\b(snbr|sleep\s*number|select\s*comfort)\b", re.I)
_INJECTION_RE = re.compile(
    r"(ignore|disregard|forget|override|bypass)\b.{0,40}"
    r"\b(instruction|prompt|rule|guardrail|above|previous|prior)"
    r"|system\s*prompt|developer\s*(message|prompt)"
    r"|\b(api|secret|access|auth|demo|bearer)[\s_-]*(key|token)s?\b"
    r"|\b(password|credential|env(ironment)?\s*var)"
    r"|\bjailbreak\b|\byou\s+are\s+now\b",
    re.I | re.S)
# Words that say the question is about a borrower's credit terms.
_COVENANT_RE = re.compile(
    r"\b(check|covenants?|leverage|credit|borrower|compliance|lender|"
    r"debt|loan|breach|ebitda|forbearance|headroom)\b", re.I)

_MONTHS = {name: number for number, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"),
    ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
    ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
    ("nov", "november"), ("dec", "december")), 1) for name in names}
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY_FORMS = (
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
                re.I), "mdy_name"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH},?\s+(\d{{4}})\b",
                re.I), "dmy_name"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy"),
)
_MONTH_YEAR_RE = re.compile(rf"\b{_MONTH},?\s+(\d{{4}})\b", re.I)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


@dataclass(frozen=True)
class Route:
    kind: str
    ticker: str | None = None
    period_end: str | None = None
    as_of: str | None = None
    prompt: str | None = None  # the only question text the model sees
    memo_note: str | None = None


def computed_tests():
    """Sleep Number test dates with computed results, oldest first."""
    pattern = re.compile(r"snbr_(\d{4}-\d{2}-\d{2})\.json")
    found = (pattern.fullmatch(p.name)
             for p in (agent.DATA_DIR / "results").glob("snbr_*.json"))
    return sorted(m.group(1) for m in found if m)


def _safe_date(year, month, day):
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def parse_asked_date(question):
    """(precision, date, label) for the first date named, or None.

    precision is day, month, or year; the date is the last day it covers.
    """
    for pattern, form in _DAY_FORMS:
        match = pattern.search(question)
        if not match:
            continue
        a, b, c = match.groups()
        if form == "ymd":
            parsed = _safe_date(a, b, c)
        elif form == "mdy_name":
            parsed = _safe_date(c, _MONTHS[a.lower()], b)
        elif form == "dmy_name":
            parsed = _safe_date(c, _MONTHS[b.lower()], a)
        else:
            parsed = _safe_date(c, a, b)
        if parsed:
            return "day", parsed, agent.prose_date(parsed.isoformat())
    match = _MONTH_YEAR_RE.search(question)
    if match:
        month, year = _MONTHS[match.group(1).lower()], int(match.group(2))
        last = calendar.monthrange(year, month)[1]
        label = f"{calendar.month_abbr[month]} {year}"
        return "month", date(year, month, last), label
    match = _YEAR_RE.search(question)
    if match:
        year = int(match.group(1))
        return "year", date(year, 12, 31), str(year)
    return None


def _listing(tests):
    names = [agent.prose_date(t) for t in tests]
    if len(names) < 2:
        return "".join(names)
    return "; ".join(names[:-1]) + "; and " + names[-1]


def choose_test(question, tests):
    """(test date, note for the memo or None), never past the chosen test."""
    asked = parse_asked_date(question)
    latest = tests[-1]
    if asked is None:
        return latest, agent.DEFAULT_DATE_LINE.format(
            period=agent.prose_date(latest))
    precision, day, label = asked
    iso = day.isoformat()
    if precision == "day" and iso in tests:
        return iso, None
    if precision == "month":
        within = [t for t in tests if t[:7] == iso[:7]]
        if within:
            return within[-1], None
    if precision == "year":
        within = [t for t in tests if t[:4] == iso[:4]]
        if within:
            chosen = within[-1]
            return chosen, (f"Using the latest computed test in {label}, "
                            f"{agent.prose_date(chosen)}.")
    if iso < tests[0]:
        return tests[0], (
            f"Onya has computed tests for {_listing(tests)}. {label} is "
            f"before the first, so this uses {agent.prose_date(tests[0])}.")
    if iso > latest:
        return latest, (
            f"Onya has computed tests for {_listing(tests)}. {label} is "
            f"after the latest, so this uses {agent.prose_date(latest)}.")
    chosen = [t for t in tests if t <= iso][-1]
    return chosen, (f"The latest computed test on or before {label} is "
                    f"{agent.prose_date(chosen)}.")


def _covered_ticker(question):
    lowered = question.lower().replace("’", "'")
    for ticker, (_name, aliases) in COVERED.items():
        # Tickers are matched in capitals: "AIN" and "trs" read differently.
        if re.search(rf"\b{ticker}\b", question):
            return ticker
        if any(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", lowered)
               for a in aliases):
            return ticker
    return None


def route_question(question, tests=None):
    """The route for a non-empty question within the length limit."""
    text = question or ""
    if _INJECTION_RE.search(text):
        return Route(ROUTE_OFF_TOPIC)
    if _SNBR_RE.search(text):
        tests = tests if tests is not None else computed_tests()
        if not tests:
            return Route(ROUTE_UNKNOWN)
        period, note = choose_test(text, tests)
        prompt = ("Check Sleep Number's covenants as of the "
                  f"{agent.prose_date(period)} test and tell me what to do.")
        return Route(ROUTE_SNBR, ticker="SNBR", period_end=period,
                     as_of=agent.reporting_as_of(period), prompt=prompt,
                     memo_note=note)
    ticker = _covered_ticker(text)
    if ticker:
        return Route(ROUTE_BACKTESTED, ticker=ticker)
    if _COVENANT_RE.search(text):
        return Route(ROUTE_UNKNOWN)
    return Route(ROUTE_OFF_TOPIC)
