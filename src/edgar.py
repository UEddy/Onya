import json
import os
import re
import socket
import sys
import time
from pathlib import Path

import requests
import urllib3.util.connection
from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textify import html_to_text  # noqa: E402

urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

load_dotenv(os.path.expanduser("~/.config/onya/.env"))

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT")
if not SEC_USER_AGENT:
    raise SystemExit("SEC_USER_AGENT missing from ~/.config/onya/.env")

RAW_DIR = Path("data/raw")

FILES = [
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718726000035/ex101thirteenthamendmentto.htm",
        "snbr_13th_amendment.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718725000123/snbr-20251110.htm",
        "snbr_8k_20251110.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718725000121/snbr-20250927.htm",
        "snbr_10q_20250927.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718725000096/a2025-q2ex991earnings.htm",
        "snbr_earnings_q2_2025.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718725000116/a2025-q3ex991earnings.htm",
        "snbr_earnings_q3_2025.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718726000012/a2025-q4ex991earnings.htm",
        "snbr_earnings_q4_2025.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/0000827187/000082718726000039/a2026-q1ex991earnings.htm",
        "snbr_earnings_q1_2026.htm",
    ),
    (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000827187.json",
        "snbr_companyfacts.json",
    ),
]


def fetch(url, filename):
    dest = RAW_DIR / filename
    if dest.exists():
        return dest
    headers = {"User-Agent": SEC_USER_AGENT}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        raise requests.HTTPError(
            f"GET {url} failed with status {resp.status_code}",
            response=resp,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    time.sleep(0.5)
    return dest


TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{accession_dashed}-index.htm"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

EXHIBIT_HEAD_CHARS = 3000
EXCLUDE_HEAD_CHARS = 500
TITLE_MAX_CHARS = 150

INCLUDE_PATTERNS = (
    r"\bcredit\s+(and\s+security\s+|and\s+guaranty\s+)?agreement\b",
    r"\bloan\s+(and\s+security\s+)?agreement\b",
    r"\brevolving\s+credit\b",
    r"\bterm\s+loan\b",
    r"\bforbearance\b",
    r"\bfinancing\s+agreement\b",
    r"\bnote\s+purchase\s+agreement\b",
)
INCLUDE_RES = tuple(re.compile(p, re.IGNORECASE) for p in INCLUDE_PATTERNS)

EXCLUDE_PATTERNS = (
    r"\blease\b",
    r"\bsublease\b",
    r"\bemployment\b",
    r"\bexecutive\b",
    r"\bseverance\b",
    r"\bseparation\b",
    r"\bcompensation\b",
    r"\bincentive\b",
    r"\baward\b",
    r"\bindemnification\b",
    r"\bconsulting\b",
    r"\bsupply\b",
    r"\blicense\b",
    r"\bmerger\b",
    r"\bpurchase\s+and\s+sale\b",
)
EXCLUDE_RES = tuple(re.compile(p, re.IGNORECASE) for p in EXCLUDE_PATTERNS)

FORBEARANCE_RE = re.compile(r"\bforbearance\b", re.IGNORECASE)
AMENDMENT_RE = re.compile(r"\bamend", re.IGNORECASE)

EXHIBIT_TYPE_RE = re.compile(r"^EX-10(\.\d+)?$", re.IGNORECASE)

TITLE_UPPER_CHARS = 1500
TITLE_KEYWORDS = ("AGREEMENT", "AMENDMENT", "FORBEARANCE")

COMPLETE_MIN_CHARS = 150000
COMPLETE_TOP_N = 5
CONSOLIDATED_EBITDA_RE = re.compile(r"consolidated\s+ebitda", re.IGNORECASE)
EBITDA_DEFINED_RE = re.compile(
    r"EBITDA[\"“”'‘’]?\W+(?:\w+\W+){0,3}?means\b", re.IGNORECASE
)
FINANCIAL_COVENANT_RES = (
    re.compile(r"financial\s+covenant", re.IGNORECASE),
    re.compile(r"leverage\s+ratio", re.IGNORECASE),
    re.compile(r"coverage\s+ratio", re.IGNORECASE),
)


def _digits(cik):
    return "".join(ch for ch in str(cik) if ch.isdigit())


def _cik_10(cik):
    digits = _digits(cik)
    if not digits:
        raise ValueError(f"Invalid CIK: {cik!r}")
    return digits.zfill(10)[-10:]


def _cik_plain(cik):
    digits = _digits(cik)
    if not digits:
        raise ValueError(f"Invalid CIK: {cik!r}")
    return str(int(digits))


def _accession_forms(accession):
    s = str(accession).strip()
    if "-" in s:
        return s.replace("-", ""), s
    nodash = s
    if len(nodash) == 18 and nodash.isdigit():
        dashed = f"{nodash[:10]}-{nodash[10:12]}-{nodash[12:]}"
    else:
        dashed = s
    return nodash, dashed


def get_cik(ticker_or_cik):
    """Return the 10-digit zero-padded CIK for a ticker symbol or numeric CIK."""
    s = str(ticker_or_cik).strip()
    if s.isdigit():
        return _cik_10(s)
    path = fetch(TICKERS_URL, "company_tickers.json")
    data = json.loads(path.read_text())
    entries = data.values() if isinstance(data, dict) else data
    want = s.upper()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("ticker")
        if isinstance(symbol, str) and symbol.strip().upper() == want:
            return _cik_10(entry.get("cik_str", ""))
    raise ValueError(
        f"Unknown ticker {ticker_or_cik!r}: company may be delisted; "
        "pass the CIK instead."
    )


def list_filings(cik, forms=("8-K", "10-K", "10-Q"), since="2024-01-01"):
    """Filings of the given forms on/after `since` (YYYY-MM-DD)."""
    cik10 = _cik_10(cik)
    path = fetch(
        SUBMISSIONS_URL.format(cik=cik10),
        f"submissions_CIK{cik10}.json",
    )
    data = json.loads(path.read_text())
    recent = (data.get("filings") or {}).get("recent") or {}
    if isinstance(forms, str):
        forms = (forms,)
    wanted = set(forms)
    forms_list = recent.get("form", [])
    items_list = recent.get("items", [])
    if not isinstance(items_list, list):
        items_list = []
    if len(items_list) < len(forms_list):
        items_list = list(items_list) + [""] * (len(forms_list) - len(items_list))
    rows = []
    for form, filing_date, accession, primary, report, items in zip(
        recent.get("form", []),
        recent.get("filingDate", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
        recent.get("reportDate", []),
        items_list,
    ):
        if form in wanted and (filing_date or "") >= since:
            rows.append(
                {
                    "form": form,
                    "filingDate": filing_date,
                    "accessionNumber": accession,
                    "primaryDocument": primary,
                    "reportDate": report,
                    "items": items or "",
                }
            )
    return rows


def _parse_index_html(html):
    soup = BeautifulSoup(html, "html.parser")
    docs = []
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue
        headers = [
            c.get_text(strip=True).lower()
            for c in header_row.find_all(["th", "td"])
        ]
        if "document" not in headers or "type" not in headers:
            continue
        try:
            desc_idx = headers.index("description")
            doc_idx = headers.index("document")
            type_idx = headers.index("type")
        except ValueError:
            continue
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(desc_idx, doc_idx, type_idx):
                continue
            desc = cells[desc_idx].get_text(strip=True)
            doc_cell = cells[doc_idx]
            link = doc_cell.find("a")
            name = (
                link.get_text(strip=True)
                if link
                else doc_cell.get_text(strip=True)
            )
            if not name:
                continue
            typ = cells[type_idx].get_text(strip=True)
            doc = {"name": name, "type": typ}
            if desc:
                doc["description"] = desc
            docs.append(doc)
    return docs


def filing_documents(cik, accession):
    """Documents in a filing: name, type, and description when present.

    Fetches the filing's ``-index.htm`` page and parses the document
    table (Seq, Description, Document, Type, Size).
    """
    cik_plain = _cik_plain(cik)
    acc_nodash, acc_dashed = _accession_forms(accession)
    path = fetch(
        FILING_INDEX_URL.format(
            cik=cik_plain,
            accession=acc_nodash,
            accession_dashed=acc_dashed,
        ),
        f"{cik_plain}_{acc_nodash}_index.htm",
    )
    html = path.read_text(encoding="utf-8", errors="replace")
    return _parse_index_html(html)


def _wants_index_page(filing):
    form = filing.get("form")
    if form in ("10-K", "10-Q"):
        return True
    if form == "8-K":
        items = filing.get("items", "")
        if isinstance(items, (list, tuple)):
            tokens = [str(x).strip() for x in items]
        else:
            tokens = [t.strip() for t in str(items or "").split(",")]
        return "1.01" in tokens or "2.03" in tokens
    return False


def _matches_any(regexes, text):
    return any(rx.search(text) for rx in regexes)


def _is_mostly_uppercase(line):
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= 0.6


def _is_complete_text(text):
    if len(text) <= COMPLETE_MIN_CHARS:
        return False
    has_ebitda = bool(CONSOLIDATED_EBITDA_RE.search(text)) or bool(
        EBITDA_DEFINED_RE.search(text)
    )
    if not has_ebitda:
        return False
    return _matches_any(FINANCIAL_COVENANT_RES, text)


def _extract_title(head):
    """Uppercase agreement/amendment/forbearance line, else INCLUDE match.

    Prefer the first line within the first 1,500 characters that is
    mostly uppercase (>=60% of letters uppercase) and contains
    AGREEMENT, AMENDMENT, or FORBEARANCE. Fall back to the first
    non-empty line matching an INCLUDE pattern, else the first
    non-empty line. Trimmed to 150 chars.
    """
    for line in head[:TITLE_UPPER_CHARS].splitlines():
        s = line.strip()
        if not s:
            continue
        if not _is_mostly_uppercase(s):
            continue
        upper = s.upper()
        if any(k in upper for k in TITLE_KEYWORDS):
            return s[:TITLE_MAX_CHARS]
    fallback = ""
    for line in head.splitlines():
        s = line.strip()
        if not s:
            continue
        if not fallback:
            fallback = s[:TITLE_MAX_CHARS]
        if _matches_any(INCLUDE_RES, s):
            return s[:TITLE_MAX_CHARS]
    return fallback


def find_credit_agreements(ticker_or_cik):
    """Candidate credit-agreement exhibits across 8-K/10-K/10-Q since 2023.

    Only 8-Ks reporting item 1.01 or 2.03 are checked, plus all 10-Ks
    and 10-Qs. Every EX-10 / EX-10.n exhibit (regex ``^EX-10(\\.\\d+)?$``,
    case-insensitive, so EX-101.* XBRL files are excluded) in the
    checked filings is fetched (cached) and its first 3,000 characters
    of text (struck-through stripped via textify) are classified
    case-insensitively: included when matching a
    credit/loan/forbearance pattern, excluded when the first 500
    characters match an unrelated-agreement pattern. Newest first,
    with forbearance/amendment flags. For the top 5 newest candidates
    the full text is read and ``is_complete`` is True when it contains
    a Consolidated EBITDA defined term (or EBITDA defined with
    "means"), a financial-covenant section (Financial Covenant,
    Leverage Ratio, or Coverage Ratio), and over 150,000 characters;
    ``char_count``/``character_count`` records the full-text length.
    """
    cik10 = get_cik(ticker_or_cik)
    cik_plain = _cik_plain(cik10)
    filings = list_filings(cik10, forms=("8-K", "10-K", "10-Q"), since="2023-01-01")
    to_check = [f for f in filings if _wants_index_page(f)]
    skipped = len(filings) - len(to_check)
    if skipped:
        print(
            f"Skipping {skipped} 8-K(s) without item 1.01/2.03; "
            f"checking {len(to_check)} of {len(filings)} filings"
        )
    total = len(to_check)
    candidates = []
    for i, filing in enumerate(to_check, 1):
        print(
            f"Checking filing {i} of {total}: "
            f"{filing['form']} {filing['filingDate']} "
            f"{filing['accessionNumber']}"
        )
        acc = filing["accessionNumber"].replace("-", "")
        try:
            docs = filing_documents(cik10, filing["accessionNumber"])
        except requests.RequestException:
            continue
        for doc in docs:
            if not EXHIBIT_TYPE_RE.match(str(doc.get("type", "")).strip()):
                continue
            name = doc.get("name", "")
            if not name:
                continue
            url = ARCHIVE_URL.format(
                cik=cik_plain, accession=acc, document=name
            )
            try:
                exhibit_path = fetch(url, f"{cik_plain}_{acc}_{name}")
            except requests.RequestException:
                continue
            try:
                head = html_to_text(exhibit_path.read_bytes())[:EXHIBIT_HEAD_CHARS]
            except OSError:
                continue
            if not head.strip():
                continue
            if _matches_any(EXCLUDE_RES, head[:EXCLUDE_HEAD_CHARS]):
                continue
            if not _matches_any(INCLUDE_RES, head):
                continue
            candidates.append(
                {
                    "url": url,
                    "filingDate": filing["filingDate"],
                    "form": filing["form"],
                    "description": doc.get("description") or name,
                    "title": _extract_title(head),
                    "is_forbearance": bool(FORBEARANCE_RE.search(head)),
                    "is_amendment": bool(AMENDMENT_RE.search(head)),
                    "_exhibit_path": exhibit_path,
                }
            )
    candidates.sort(key=lambda c: c["filingDate"], reverse=True)
    for i, cand in enumerate(candidates):
        path = cand.pop("_exhibit_path", None)
        if i < COMPLETE_TOP_N and path is not None:
            try:
                full_text = html_to_text(Path(path).read_bytes())
            except OSError:
                full_text = ""
            n = len(full_text)
            cand["is_complete"] = bool(full_text and _is_complete_text(full_text))
            cand["char_count"] = n
            cand["character_count"] = n
        else:
            cand["is_complete"] = False
            cand["char_count"] = 0
            cand["character_count"] = 0
    return candidates


def discover(ticker_or_cik, limit=10):
    """Top `limit` credit-agreement candidates for a ticker or CIK, newest first."""
    return find_credit_agreements(ticker_or_cik)[:limit]


def format_candidate(i, cand):
    markers = ""
    if cand.get("is_forbearance"):
        markers += " [FORBEARANCE]"
    if cand.get("is_amendment"):
        markers += " [AMENDMENT]"
    title = cand.get("title") or cand["description"]
    return (
        f"{i}. {cand['filingDate']} {cand['form']}{markers} - {title}\n"
        f"   {cand['description']}\n"
        f"   {cand['url']}"
    )


def run_discover_cli(ticker_or_cik):
    found = discover(ticker_or_cik)
    if not found:
        print(f"No credit-agreement candidates found for {ticker_or_cik}.")
    for i, cand in enumerate(found, 1):
        print(format_candidate(i, cand))


class AgreementSelection(tuple):
    """(base, amendments) from select_agreement with dict-style access.

    Supports tuple unpacking (``base, amendments = select_agreement(...)``),
    integer indexing, and ``result["base"]`` / ``result["amendments"]``
    (plus ``base_document`` aliases, attributes, and ``get``).
    """

    _ALIASES = {
        "base": 0,
        "base_document": 0,
        "document": 0,
        "agreement": 0,
        "amendments": 1,
        "amendment_list": 1,
    }

    def __new__(cls, base, amendments):
        return super().__new__(cls, (base, amendments))

    @property
    def base(self):
        return self[0]

    @property
    def base_document(self):
        return self[0]

    @property
    def document(self):
        return self[0]

    @property
    def amendments(self):
        return self[1]

    def __getitem__(self, key):
        if isinstance(key, str) and key in self._ALIASES:
            return super().__getitem__(self._ALIASES[key])
        return super().__getitem__(key)

    def __contains__(self, key):
        if isinstance(key, str) and key in self._ALIASES:
            return True
        return super().__contains__(key)

    def get(self, key, default=None):
        if isinstance(key, str) and key in self._ALIASES:
            return super().__getitem__(self._ALIASES[key])
        try:
            return self[key]
        except (IndexError, KeyError, TypeError):
            return default

    def keys(self):
        return ["base", "amendments"]

    def values(self):
        return [self[0], self[1]]

    def items(self):
        return [("base", self[0]), ("amendments", self[1])]


def _as_of_str(as_of):
    if as_of is None:
        return None
    if hasattr(as_of, "isoformat"):
        s = as_of.isoformat()
        return s[:10]
    return str(as_of).strip()[:10]


def select_agreement(ticker_or_cik, as_of=None):
    """Newest complete agreement on/before as_of plus newer amendments.

    Base is the newest candidate with ``is_complete`` True filed on or
    before ``as_of`` (YYYY-MM-DD, None means no upper bound).
    Amendments are candidates filed after the base and on/before
    ``as_of`` with ``is_amendment`` True and ``is_complete`` falsy,
    oldest first so they apply in order after the base.
    Returns AgreementSelection(base, amendments); base is None when no
    complete candidate qualifies.
    """
    cutoff = _as_of_str(as_of)
    cands = find_credit_agreements(ticker_or_cik)
    if cutoff:
        cands = [c for c in cands if (c.get("filingDate") or "") <= cutoff]
    base = next((c for c in cands if c.get("is_complete")), None)
    if base is None:
        return AgreementSelection(None, [])
    base_date = base.get("filingDate") or ""
    amendments = [
        c
        for c in cands
        if (c.get("filingDate") or "") > base_date
        and c.get("is_amendment")
        and not c.get("is_complete")
    ]
    amendments.sort(key=lambda c: c.get("filingDate") or "")
    return AgreementSelection(base, amendments)


def format_select_candidate(cand):
    markers = ""
    if cand.get("is_forbearance"):
        markers += " [FORBEARANCE]"
    if cand.get("is_amendment"):
        markers += " [AMENDMENT]"
    title = cand.get("title") or cand.get("description", "")
    n = cand.get("char_count", cand.get("character_count", 0))
    return (
        f"{cand.get('filingDate')} {cand.get('form')}{markers} - {title}\n"
        f"   {cand.get('description')}\n"
        f"   {cand.get('url')}\n"
        f"   is_complete: {bool(cand.get('is_complete'))}, "
        f"char_count: {n}, character_count: {n} ({n} characters)"
    )


def run_select_cli(ticker_or_cik, as_of=None):
    base, amendments = select_agreement(ticker_or_cik, as_of=as_of)
    if base is None:
        print(f"No complete agreement found for {ticker_or_cik}.")
        return
    print("Base agreement:")
    print(format_select_candidate(base))
    print(f"Amendments to apply ({len(amendments)}):")
    for i, cand in enumerate(amendments, 1):
        print(f"{i}. {format_select_candidate(cand)}")


def main():
    succeeded = 0
    failed = 0
    for url, filename in FILES:
        try:
            path = fetch(url, filename)
        except requests.RequestException as e:
            resp = getattr(e, "response", None)
            status = resp.status_code if resp is not None else "unknown"
            print(f"{filename}: FAILED (HTTP {status})")
            failed += 1
            continue
        size_kb = path.stat().st_size / 1024
        print(f"{filename}: {size_kb:.2f} KB")
        succeeded += 1
    print(f"Done: {succeeded} succeeded, {failed} failed")
    return succeeded, failed


USAGE = (
    "Usage: python edgar.py discover <TICKER-or-CIK>\n"
    "   or: python edgar.py select <TICKER-or-CIK> [as_of YYYY-MM-DD]"
)


def main_cli(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) <= 1:
        return main()
    cmd = argv[1]
    if cmd == "discover":
        if len(argv) < 3:
            print("Usage: python edgar.py discover <TICKER-or-CIK>", file=sys.stderr)
            raise SystemExit(2)
        run_discover_cli(argv[2])
    elif cmd == "select":
        if len(argv) < 3:
            print(
                "Usage: python edgar.py select <TICKER-or-CIK> [as_of YYYY-MM-DD]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        as_of = argv[3] if len(argv) > 3 else None
        run_select_cli(argv[2], as_of=as_of)
    else:
        print(USAGE, file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    print(f"Using User-Agent: {SEC_USER_AGENT}")
    main_cli()
