"""Onya demo API: read-only covenant data plus background agent runs.

Read-only endpoints serve JSON straight from ``data/`` (backtest
disclosures and terms, SNBR covenant results, release tables, the
reviewed contract extraction, and the local XBRL companyfacts dump).
``POST /agent/run`` starts an ``agent.run_agent`` run in a background
thread and ``GET /agent/run/{run_id}`` serves the trace for polling.

Security: CORS allows only http://localhost:3000 plus an optional
ONYA_FRONTEND_ORIGIN value; agent runs require the X-Onya-Token
header to match ONYA_DEMO_TOKEN from ~/.config/onya/.env; responses
never include file paths, environment values, or raw model payloads.

Run from the project root::

    source .venv/bin/activate
    uvicorn api:app --app-dir src --port 8000
"""

import json
import os
import re
import secrets
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv(os.path.expanduser("~/.config/onya/.env"))

import agent  # noqa: E402
import score_disclosed  # noqa: E402
import xbrl  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BACKTEST_DIR = DATA_DIR / "backtest"
RESULTS_DIR = DATA_DIR / "results"
EXTRACTED_DIR = DATA_DIR / "extracted"
RUNS_DIR = DATA_DIR / "runs"

SNBR = "snbr"
LOCAL_ORIGIN = "http://localhost:3000"

# Rate limits for POST /agent/run.
MAX_RUNS_PER_HOUR_PER_IP = 5
MAX_RUNS_PER_DAY_TOTAL = 30

MAX_QUESTION_CHARS = 4000

# Terms-table status literals (mirrors src/backtest_terms.py, which is not
# imported here because it pulls in edgar's network/credential setup).
TERMS_STATUS_OK = "ok"
TERMS_AMENDED = "amended after agreement"
TERMS_NO_DISCLOSED = "no disclosed match"

RUN_ID_RE = re.compile(r"[0-9a-fA-F-]{1,64}\Z")
PERIOD_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

router = APIRouter()


# ---------------------------------------------------------------------------
# Safe reads (data/ only) and output redaction
# ---------------------------------------------------------------------------

def _data_file(*parts):
    """Resolve a path under data/, refusing escapes."""
    path = (DATA_DIR.joinpath(*parts)).resolve()
    if path != DATA_DIR and DATA_DIR not in path.parents:
        raise ValueError(f"path escapes data/: {parts!r}")
    return path


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_HOME = os.path.expanduser("~")

_REDACT_RES = (
    re.compile(re.escape(str(PROJECT_ROOT)) + r"[^\s\"'`,;]*"),
    re.compile(re.escape(_HOME) + r"[^\s\"'`,;]*"),
    re.compile(r"/home/[^\s\"'`,;]+"),
    re.compile(r"/tmp/[^\s\"'`,;]+"),
    re.compile(r"~\/[^\s\"'`,;]+"),
    re.compile(r"(?<![\w/])(?:data|src|tests)/[\w\-.]+(?:/[\w\-.]+)*"),
)

REDACTED = "[redacted]"


def redact(text):
    """Strip file paths from text before it leaves the API."""
    if not isinstance(text, str):
        return text
    for rx in _REDACT_RES:
        text = rx.sub(REDACTED, text)
    return text


def _redact_json(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Company names (from data/ only)
# ---------------------------------------------------------------------------

_NAME_CACHE = {}


def _cik_from_case(case):
    if case.get("cik"):
        digits = "".join(ch for ch in str(case["cik"]) if ch.isdigit())
        if digits:
            return str(int(digits))
    m = re.search(r"/data/(\d+)/", case.get("filing_url") or "")
    if m:
        return str(int(m.group(1)))
    return None


def _name_from_edgar_index(cik):
    """Newest EDGAR filing index for a CIK -> filer company name."""
    files = sorted(DATA_DIR.glob(f"raw/{cik}_*_index.htm"), reverse=True)
    want = str(int(cik)).zfill(10)
    for path in files[:5]:
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        spans = re.findall(
            r'<span class="companyName">(.*?)</span>', html, re.DOTALL)
        for span in spans:
            text = re.sub(r"<[^>]+>", " ", span)
            text = re.sub(r"\s+", " ", text).strip()
            if want not in text.replace(" ", ""):
                continue
            name = text.split("(Filer)")[0].strip()
            if name:
                return name
        for span in spans:
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", span)).strip()
            name = text.split("(Filer)")[0].strip()
            if name:
                return name
    return None


def company_name(case):
    """Display name for a backtest case, cached; falls back to ticker."""
    ticker = case["ticker"]
    if ticker in _NAME_CACHE:
        return _NAME_CACHE[ticker]
    name = None
    try:
        registry = _read_json(DATA_DIR / "companies.json")
        info = registry.get(ticker) or registry.get(ticker.upper()) or {}
        name = info.get("name") or None
    except (OSError, ValueError):
        name = None
    if not name:
        cik = _cik_from_case(case)
        if cik:
            try:
                name = _name_from_edgar_index(cik)
            except (OSError, ValueError):
                name = None
    if not name:
        name = ticker
    _NAME_CACHE[ticker] = name
    return name


# ---------------------------------------------------------------------------
# Agent-run registry and rate limiting (in-memory, thread-safe)
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_RUNS = {}
_RUN_STARTS = []
_IP_STARTS = {}


def _utcnow():
    return datetime.now(timezone.utc)


def _prune(now):
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)
    global _RUN_STARTS
    _RUN_STARTS = [t for t in _RUN_STARTS if t > day_ago]
    for ip in list(_IP_STARTS):
        kept = [t for t in _IP_STARTS[ip] if t > hour_ago]
        if kept:
            _IP_STARTS[ip] = kept
        else:
            del _IP_STARTS[ip]


def _reset_state():
    """Clear runs and rate-limit counters (tests only)."""
    with _LOCK:
        _RUNS.clear()
        _RUN_STARTS.clear()
        _IP_STARTS.clear()
    _NAME_CACHE.clear()


def _estimate_tokens(question):
    """Worst case for opening a run: prompt chars plus one full turn."""
    return len(question) // 4 + agent.MAX_TOKENS


def _expected_token():
    return os.environ.get("ONYA_DEMO_TOKEN") or ""


def _run_in_background(run_id, question):
    try:
        outcome = agent.run_agent(question, run_id=run_id)
    except SystemExit:
        with _LOCK:
            rec = _RUNS.get(run_id)
            if rec is not None:
                rec.update(status="error", reason="error",
                           error="model credentials not configured")
        return
    except Exception as exc:  # never leak tracebacks or paths to the UI
        with _LOCK:
            rec = _RUNS.get(run_id)
            if rec is not None:
                rec.update(status="error", reason="error",
                           error=redact(f"{type(exc).__name__}: {exc}"))
        return
    with _LOCK:
        rec = _RUNS.get(run_id)
        if rec is not None:
            rec.update(status="done", reason=outcome.get("reason", "done"),
                       answer=outcome.get("answer", ""),
                       total_tokens=outcome.get("total_tokens", 0),
                       tool_calls=outcome.get("tool_calls", 0))


def _read_trace(run_id):
    """Sanitized trace steps from data/runs/<run_id>.jsonl."""
    try:
        path = _data_file("runs", f"{run_id}.jsonl")
    except ValueError:
        return None
    if not path.exists():
        return None
    steps = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        steps.append({
            "step": entry.get("step"),
            "timestamp": entry.get("timestamp"),
            "type": entry.get("type"),
            "tool": entry.get("tool"),
            "arguments": _redact_json(entry.get("arguments") or {}),
            "result_summary": redact(entry.get("result_summary") or ""),
            "total_tokens": entry.get("total_tokens", 0),
        })
    return steps


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health")
def get_health():
    return {"status": "ok"}


def _primary_covenant(covenants):
    """Headline covenant: first max-direction (leverage), else first."""
    if not covenants:
        return None
    for cov in covenants:
        if cov.get("direction") == "max":
            return cov
    return covenants[0]


def _headroom(cov):
    actual = (cov or {}).get("actual")
    threshold = (cov or {}).get("threshold")
    if actual is None or threshold is None:
        return None
    if isinstance(actual, bool) or isinstance(threshold, bool):
        return None
    if cov.get("direction") == "min":
        return actual - threshold
    return threshold - actual


@router.get("/companies")
def list_companies():
    cases = _read_json(BACKTEST_DIR / "companies.json")
    companies = []
    for case in cases:
        ticker = case["ticker"]
        try:
            disclosed = score_disclosed.load_disclosed(ticker)
        except (OSError, ValueError):
            disclosed = None
        covs = (disclosed or {}).get("covenants", []) or []
        primary = _primary_covenant(covs)
        if primary is None:
            status = "unknown"
        elif primary.get("in_compliance") is True:
            status = "pass"
        elif primary.get("in_compliance") is False:
            status = "fail"
        else:
            status = "unknown"
        companies.append({
            "ticker": ticker,
            "name": company_name(case),
            "period_end": (disclosed or {}).get("period_end")
            or case.get("period_end"),
            "covenant": (primary or {}).get("name"),
            "ratio": (primary or {}).get("actual"),
            "threshold": (primary or {}).get("threshold"),
            "headroom": _headroom(primary),
            "status": status,
        })
    return {"companies": companies}


def _require_snbr(ticker):
    if str(ticker or "").lower() != SNBR:
        return JSONResponse(status_code=404,
                            content={"detail": "unsupported company"})
    return None


def _compact_verdict(block):
    block = block or {}
    return {"ratio": block.get("ratio"), "ratio_2dp": block.get("ratio_2dp"),
            "threshold": block.get("threshold"),
            "headroom": block.get("headroom"),
            "headroom_2dp": block.get("headroom_2dp"),
            "pass": block.get("pass")}


@router.get("/company/{ticker}/periods")
def list_periods(ticker: str):
    denied = _require_snbr(ticker)
    if denied is not None:
        return denied
    periods = []
    files = sorted(RESULTS_DIR.glob("snbr_*.json"))
    for path in files:
        if path.name.startswith("snbr_projection_"):
            continue
        try:
            result = _read_json(path)
        except (OSError, ValueError):
            continue
        periods.append({
            "period_end": result.get("period_end"),
            "net_leverage": _compact_verdict(result.get("net_leverage")),
            "interest_coverage": _compact_verdict(
                result.get("interest_coverage")),
            "scenarios": result.get("proforma_scenarios"),
        })
    periods.sort(key=lambda p: p["period_end"] or "")
    return {"ticker": "SNBR", "periods": periods}


@router.get("/company/{ticker}/period/{period_end}")
def get_period(ticker: str, period_end: str):
    denied = _require_snbr(ticker)
    if denied is not None:
        return denied
    if not PERIOD_RE.match(period_end):
        return JSONResponse(status_code=404,
                            content={"detail": "unknown period"})
    try:
        result = _read_json(_data_file("results", f"snbr_{period_end}.json"))
    except (OSError, ValueError):
        return JSONResponse(status_code=404,
                            content={"detail": "unknown period"})
    try:
        projection = _read_json(
            _data_file("results", f"snbr_projection_{period_end}.json"))
    except (OSError, ValueError):
        projection = None
    rec = result.get("reconciliation")
    flags = {
        "data_quality_warnings": result.get("data_quality_warnings", []),
        "warning_count": len(result.get("data_quality_warnings", []) or []),
        "reconciliation": (rec if rec is not None
                           else agent.RECONCILIATION_UNAVAILABLE),
        "unverifiable_proforma": bool(result.get("proforma_scenarios")),
    }
    body = dict(result)
    body["flags"] = flags
    body["scenarios"] = result.get("proforma_scenarios")
    body["projection"] = projection
    return body


def _contract_evidence(clause_refs):
    contract = _read_json(EXTRACTED_DIR / "snbr_covenants.reviewed.json")
    by_ref = {}
    for definition in contract.get("definitions", []):
        for comp in definition.get("components", []):
            ref = comp.get("clause_ref")
            if ref and ref not in by_ref:
                by_ref[ref] = (definition, comp)
    clauses = []
    for ref in clause_refs:
        hit = by_ref.get(ref)
        if hit is None:
            return None
        definition, comp = hit
        clauses.append({
            "clause_ref": ref,
            "term": definition.get("term"),
            "section": definition.get("section"),
            "label": comp.get("label"),
            "quote": comp.get("quote"),
        })
    return clauses


def _xbrl_evidence(concept, period_end):
    try:
        data = xbrl.load_facts()
    except (OSError, ValueError):
        return None, None
    if ":" in concept:
        ns, name = concept.split(":", 1)
    else:
        ns, name = "us-gaap", concept
    entry = (data.get("facts", {}).get(ns, {}) or {}).get(name)
    if entry is None:
        return None, None
    facts = []
    for unit, unit_facts in (entry.get("units", {}) or {}).items():
        for fact in unit_facts or []:
            if fact.get("form") not in xbrl.ALLOWED_FORMS:
                continue
            facts.append((fact.get("end"), fact.get("start"), unit, fact))
    best = {}
    for end, start, unit, fact in facts:
        key = (end, start, unit)
        if (key not in best
                or (fact.get("filed", "") or "")
                >= (best[key].get("filed", "") or "")):
            best[key] = fact
    rows = []
    for (end, start, unit), fact in best.items():
        if period_end is not None and (end or "") > period_end:
            continue
        row = {"val": fact.get("val"), "end": end, "unit": unit,
               "form": fact.get("form"), "filed": fact.get("filed")}
        if start:
            row["start"] = start
        rows.append(row)
    rows.sort(key=lambda r: (r["end"] or "", r.get("start") or ""),
              reverse=True)
    return entry.get("label"), rows[:12]


def _result_component_value(period_end, source):
    try:
        result = _read_json(_data_file("results", f"snbr_{period_end}.json"))
    except (OSError, ValueError):
        return None
    for comp in result.get("components", []) or []:
        if comp.get("source") == source:
            return comp.get("value")
    return None


def _release_evidence(line, period_end):
    if period_end is not None:
        paths = [EXTRACTED_DIR / f"snbr_release_{period_end}.json"]
    else:
        paths = sorted(EXTRACTED_DIR.glob("snbr_release_*.json"))
    matches = []
    for path in paths:
        try:
            release = _read_json(path)
        except (OSError, ValueError):
            continue
        for table in ("adjusted_ebitda_ttm", "leverage_table_ttm"):
            for row in release.get(table, []) or []:
                if row.get("line") == line:
                    matches.append({
                        "period_end": release.get("period_end"),
                        "table": table,
                        "line": row.get("line"),
                        "value_thousands": row.get("value_thousands"),
                        "quote": row.get("quote"),
                    })
    return matches


@router.get("/source")
def get_source(ref: str = Query(...),
               period_end: str | None = Query(default=None)):
    if period_end is not None and not PERIOD_RE.match(period_end):
        return JSONResponse(status_code=400,
                            content={"detail": "invalid period_end"})
    kind, sep, rest = ref.partition(":")
    if not sep or not rest:
        return JSONResponse(status_code=400,
                            content={"detail": "invalid ref"})
    if kind == "contract":
        clause_refs = [c for c in rest.split("+") if c]
        if not clause_refs:
            return JSONResponse(status_code=400,
                                content={"detail": "invalid ref"})
        try:
            clauses = _contract_evidence(clause_refs)
        except (OSError, ValueError):
            return JSONResponse(status_code=404,
                                content={"detail": "contract data missing"})
        if clauses is None:
            return JSONResponse(status_code=404,
                                content={"detail": "clause not found"})
        return {"ref": ref, "kind": "contract", "clauses": clauses}
    if kind == "xbrl":
        try:
            label, facts = _xbrl_evidence(rest, period_end)
        except (OSError, ValueError):
            return JSONResponse(status_code=404,
                                content={"detail": "XBRL data missing"})
        if facts is None:
            return JSONResponse(status_code=404,
                                content={"detail": "concept not found"})
        value = (_result_component_value(period_end, ref)
                 if period_end else None)
        return {"ref": ref, "kind": "xbrl", "concept": rest, "label": label,
                "value": value, "period_end": period_end, "facts": facts}
    if kind == "release":
        matches = _release_evidence(rest, period_end)
        if not matches:
            return JSONResponse(status_code=404,
                                content={"detail": "release line not found"})
        return {"ref": ref, "kind": "release", "matches": matches}
    return JSONResponse(status_code=400,
                        content={"detail": f"unsupported ref kind: {kind}"})


@router.get("/backtest")
def get_backtest():
    key = score_disclosed.load_key()
    rows = []
    notes = []
    for ticker in sorted(key):
        try:
            ext = score_disclosed.load_disclosed(ticker)
        except (OSError, ValueError):
            ext = None
        if ext is None:
            notes.append(f"{ticker} has no disclosed_{ticker}.json; "
                         "all rows miss")
        company_rows, extras = score_disclosed.score_company(
            ticker, key[ticker], ext)
        rows.extend(company_rows)
        for name in extras:
            notes.append(f"{ticker} extra extraction not in key: {name}")
    n = len(rows)
    disclosed_totals = {
        "covenants": n,
        "actual_matched": sum(1 for r in rows if r["actual_match"]),
        "threshold_matched": sum(1 for r in rows if r["threshold_match"]),
        "fully_matched": sum(1 for r in rows
                             if r["actual_match"] and r["threshold_match"]),
        "matched": sum(1 for r in rows if r["matched"]),
        "verified": sum(1 for r in rows if r["verified"]),
        "matched_and_verified": sum(1 for r in rows
                                    if r["matched_and_verified"]),
    }

    cases = _read_json(BACKTEST_DIR / "companies.json")
    term_rows = []
    records = []
    term_notes = []
    for case in cases:
        ticker = case["ticker"]
        if ticker.upper() == "SNBR":
            continue
        try:
            record = _read_json(_data_file("backtest", f"terms_{ticker}.json"))
        except (OSError, ValueError):
            records.append({"ticker": ticker,
                            "period_end": case.get("period_end"),
                            "status": "missing"})
            term_notes.append(f"{ticker} has no terms_{ticker}.json")
            continue
        records.append({"ticker": ticker,
                        "period_end": record.get("period_end"),
                        "status": record.get("status")})
        if record.get("status") != TERMS_STATUS_OK:
            term_notes.append(f"{ticker} status: {record.get('status')}")
        for cov in record.get("covenants", []) or []:
            row = dict(cov)
            row["ticker"] = ticker
            term_rows.append(row)
    m = len(term_rows)
    matched = sum(1 for r in term_rows if r.get("match"))
    amended = sum(1 for r in term_rows if r.get("status") == TERMS_AMENDED)
    no_disclosed = sum(1 for r in term_rows
                       if r.get("status") == TERMS_NO_DISCLOSED)
    terms_totals = {
        "covenants": m,
        "companies": len(records),
        "matched": matched,
        "amended_after_agreement": amended,
        "no_disclosed_match": no_disclosed,
        "mismatched": m - matched - amended - no_disclosed,
        "quote_verified": sum(1 for r in term_rows
                              if r.get("quote_verified")),
    }
    return {"disclosed": {"rows": rows, "totals": disclosed_totals,
                          "notes": notes},
            "terms": {"rows": term_rows, "totals": terms_totals,
                      "records": records, "notes": term_notes}}


class RunRequest(BaseModel):
    question: str


@router.post("/agent/run", status_code=202)
def start_agent_run(body: RunRequest, request: Request,
                    x_onya_token: str | None = Header(default=None)):
    expected = _expected_token()
    if not expected:
        return JSONResponse(status_code=500,
                            content={"detail": "server token not configured"})
    if not secrets.compare_digest(x_onya_token or "", expected):
        return JSONResponse(status_code=401,
                            content={"detail": "invalid token"})
    question = (body.question or "").strip()
    if not question:
        return JSONResponse(status_code=422,
                            content={"detail": "question is required"})
    if len(question) > MAX_QUESTION_CHARS:
        return JSONResponse(status_code=413,
                            content={"detail": "question too long"})
    if _estimate_tokens(question) > agent.TOKEN_BUDGET:
        return JSONResponse(
            status_code=429,
            content={"detail": "per-run token budget would be exceeded"})
    ip = request.client.host if request.client else "unknown"
    now = _utcnow()
    with _LOCK:
        _prune(now)
        if len(_IP_STARTS.get(ip, [])) >= MAX_RUNS_PER_HOUR_PER_IP:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit: 5 runs per hour per IP"})
        if len(_RUN_STARTS) >= MAX_RUNS_PER_DAY_TOTAL:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit: 30 runs per day total"})
        run_id = uuid.uuid4().hex[:12]
        _RUNS[run_id] = {"run_id": run_id, "question": question,
                         "status": "running", "reason": None, "answer": None,
                         "total_tokens": 0, "tool_calls": 0, "error": None,
                         "started_at": now.isoformat(), "ip": ip}
        _RUN_STARTS.append(now)
        _IP_STARTS.setdefault(ip, []).append(now)
    thread = threading.Thread(target=_run_in_background,
                              args=(run_id, question), daemon=True)
    thread.start()
    return {"run_id": run_id, "status": "running"}


@router.get("/agent/run/{run_id}")
def get_agent_run(run_id: str):
    if not RUN_ID_RE.match(run_id):
        return JSONResponse(status_code=404,
                            content={"detail": "unknown run"})
    with _LOCK:
        record = dict(_RUNS.get(run_id, {}))
    steps = _read_trace(run_id)
    if not record and not steps:
        return JSONResponse(status_code=404,
                            content={"detail": "unknown run"})
    steps = steps or []
    if record:
        status = record["status"]
        reason = record.get("reason")
        answer = record.get("answer")
        total_tokens = record.get("total_tokens", 0)
        tool_calls = record.get("tool_calls", 0)
        error = record.get("error")
    else:
        reason = None
        status = "done" if steps else "running"
        answer = None
        total_tokens = steps[-1].get("total_tokens", 0) if steps else 0
        tool_calls = sum(1 for s in steps if s.get("type") == "tool_call")
        error = None
    return {"run_id": run_id, "status": status, "reason": reason,
            "steps": steps,
            "answer": redact(answer) if answer else None,
            "total_tokens": total_tokens, "tool_calls": tool_calls,
            "error": redact(error) if error else None}


def allowed_origins():
    origins = [LOCAL_ORIGIN]
    extra = (os.environ.get("ONYA_FRONTEND_ORIGIN") or "").strip()
    if extra and extra not in origins:
        origins.append(extra)
    return origins


def create_app():
    app = FastAPI(title="Onya demo API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["X-Onya-Token", "Content-Type"],
        allow_credentials=False,
        max_age=600,
    )
    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
