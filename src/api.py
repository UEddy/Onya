"""Onya demo API: read-only covenant data plus a streamed agent run.

Read-only endpoints serve JSON straight from ``data/`` (backtest
disclosures and terms, SNBR covenant results, release tables, the
reviewed contract extraction, and the local XBRL companyfacts dump).
``POST /agent/run`` validates the token, rate limits and budget, then
streams the run inside the request as newline-delimited JSON events
(serverless instances freeze after the response: no background
threads, no polling).

Security: CORS allows only http://localhost:3000 plus an optional
ONYA_FRONTEND_ORIGIN value; agent runs require the X-Onya-Token
header to match ONYA_DEMO_TOKEN from ~/.config/onya/.env; responses
never include file paths, environment values, or raw model payloads.

Run from the project root (same entrypoint Vercel uses)::

    source .venv/bin/activate
    uvicorn app:app --port 8000
"""

import json
import logging
import os
import queue
import re
import secrets
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv(os.path.expanduser("~/.config/onya/.env"))

import secret_files  # noqa: E402

secret_files.load_secret_files()

import agent  # noqa: E402
import limits  # noqa: E402
import score_disclosed  # noqa: E402
import xbrl  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BACKTEST_DIR = DATA_DIR / "backtest"
RESULTS_DIR = DATA_DIR / "results"
EXTRACTED_DIR = DATA_DIR / "extracted"

log = logging.getLogger("onya.api")

HEARTBEAT_SECONDS = 10
# After the run's own 270 s deadline, before the 300 s function cap.
STREAM_WATCHDOG_SECONDS = 278
FINAL_EVENT_TYPES = {"run_result", "private_result", "error"}
LOST_MESSAGE = ("The check ended without a result. Nothing was completed. "
                "Please try again.")
RUN_FAILED_MESSAGE = ("The check failed unexpectedly. Nothing was completed. "
                      "Please try again.")
PRIVATE_MODEL_FAILED_MESSAGE = ("The comparison model did not answer. "
                                "Nothing was completed. Please try again.")
REQUEST_TOO_LONG_MESSAGE = ("The request draft took too long without "
                            "finishing. Please try again.")
PRIVATE_TOO_LONG_MESSAGE = ("The comparison took too long without finishing. "
                            "Nothing was completed. Please try again.")

SNBR = "snbr"
LOCAL_ORIGIN = "http://localhost:3000"

MAX_QUESTION_CHARS = 4000

# Terms-table status literals (mirrors src/backtest_terms.py, which is not
# imported here because it pulls in edgar's network/credential setup).
TERMS_STATUS_OK = "ok"
TERMS_AMENDED = "amended after agreement"
TERMS_NO_DISCLOSED = "no disclosed match"

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


COMPANY_NAME_OVERRIDES = {
    "SNBR": "Sleep Number",
    "GPK": "Graphic Packaging",
    "HAIN": "Hain Celestial",
    "NUVR": "Nuvera Communications",
    "STGW": "Stagwell",
    "AMCX": "AMC Networks",
    "ORLY": "O'Reilly Automotive",
    "QUAD": "Quad",
    "TRS": "TriMas",
    "AIN": "Albany International",
    "CRS": "Carpenter Technology",
    "OPTX": "Syntec Optics",
}


def clean_company_name(ticker, raw_name):
    """Title-case display name, with a small override map for known names."""
    if ticker in COMPANY_NAME_OVERRIDES:
        return COMPANY_NAME_OVERRIDES[ticker]
    name = re.sub(r"\s+", " ", str(raw_name or ticker)).strip()
    name = re.sub(r"\s*/DE/\s*$", "", name)
    name = re.sub(r",?\s+(CORP|INC|INC\.|CORPORATION|CO|HOLDINGS, INC\.|"
                  r"HOLDING CO)\.?$", "", name, flags=re.IGNORECASE)
    return name.title() if name.isupper() else name


def normalize_covenant_name(name):
    """Short sentence-case covenant label for display."""
    if not name:
        return None
    low = re.sub(r"\s+", " ", str(name).lower()).strip()
    if "debt service" in low:
        return "Debt service coverage"
    if "fixed charge" in low:
        return "Fixed charge coverage"
    if "secured leverage" in low:
        return "Secured leverage"
    if "net leverage" in low:
        return "Net leverage"
    if "interest coverage" in low or "interest expense" in low:
        return "Interest coverage"
    if "leverage" in low:
        return "Total leverage"
    if "ebitda" in low:
        return "Consolidated EBITDA"
    text = low
    for prefix in ("consolidated ", "minimum ", "maximum "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = re.sub(r"\s+ratio$", "", text)
    return text[:1].upper() + text[1:] if text else None


# ---------------------------------------------------------------------------
# Agent limits live in Redis in production (see limits.py); locally an
# in-memory store stands in. Runs stream inside the request: serverless
# instances freeze after the response, so there are no background
# threads and no shared run registry.
# ---------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc)


def _reset_state():
    """Clear cached company names and local limit counters (tests only)."""
    _NAME_CACHE.clear()
    limits.reset_local()


def _estimate_tokens(question):
    """Worst case for opening a run: prompt chars plus one full turn."""
    return len(question) // 4 + agent.MAX_TOKENS


def _expected_token():
    return os.environ.get("ONYA_DEMO_TOKEN") or ""


def _paused():
    """Fail-closed answer when limits cannot be enforced."""
    return JSONResponse(
        status_code=503,
        content={"detail": "The live agent is paused."})


def _claim_limits(store, ip):
    """Atomically claim one run; returns an error response or None."""
    try:
        hour_runs = store.claim(limits.ip_key(ip), 3600)
    except limits.RedisUnavailable:
        return _paused()
    if hour_runs > limits.MAX_RUNS_PER_HOUR_PER_IP:
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit: 5 runs per hour per IP"})
    try:
        day_runs = store.claim(limits.day_key(), 2 * 86400)
    except limits.RedisUnavailable:
        return _paused()
    if day_runs > limits.MAX_RUNS_PER_DAY_TOTAL:
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit: 30 runs per day total"})
    return None


def _budget_exhausted(store):
    """True when the daily token budget is spent (fail closed on error)."""
    try:
        spent = store.total(limits.tokens_key())
    except limits.RedisUnavailable:
        return True
    return spent >= _daily_token_budget()


def _agent_replay_enabled():
    """True only when ONYA_AGENT_REPLAY=1 (never on unless explicitly set)."""
    return os.environ.get("ONYA_AGENT_REPLAY") == "1"


def _is_production():
    return os.environ.get("ONYA_ENV") == "production"


def _agent_enabled():
    return (os.environ.get("ONYA_AGENT_ENABLED") or "1").strip().lower() \
        not in {"0", "false", "off", "no"}


def _daily_token_budget():
    try:
        return int(os.environ.get("ONYA_DAILY_TOKEN_BUDGET") or 1500000)
    except ValueError:
        return 1500000


def _record_tokens(store, total_tokens):
    """Add a finished run's tokens to the daily budget (best effort)."""
    try:
        total = int(total_tokens or 0)
    except (TypeError, ValueError):
        return
    if total <= 0:
        return
    try:
        store.add(limits.tokens_key(), total, 2 * 86400)
    except Exception as exc:  # a result must not be lost over its count
        log.warning("token count not recorded: %s", type(exc).__name__)


class _TokenMeter:
    """Counts a run's tokens as they are spent, not when its stream ends.

    A closed tab or dropped connection stops the stream, but the worker
    keeps spending, so counting only at the end would miss that spend.
    """

    def __init__(self, store):
        self._store = store
        self._lock = threading.Lock()
        self._recorded = 0

    def up_to(self, total):
        """Record the run's running total; safe to repeat."""
        if isinstance(total, bool) or not isinstance(total, int):
            return
        with self._lock:
            delta = total - self._recorded
            if delta <= 0:
                return
            self._recorded = total
        _record_tokens(self._store, delta)


def _client_ip(request, token_valid):
    """Visitor IP: forwarded header trusted only with a valid token."""
    if token_valid:
        forwarded = request.headers.get("x-onya-client-ip")
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _load_sample_memo():
    try:
        return _read_json(_data_file("samples", "snbr_memo.json"))
    except (OSError, ValueError):
        return None


def _sanitize_step(entry):
    """Trace entry safe for the browser (no paths or raw payloads)."""
    if not isinstance(entry, dict):
        return None
    return {
        "step": entry.get("step"),
        "timestamp": entry.get("timestamp"),
        "type": entry.get("type"),
        "tool": entry.get("tool"),
        "arguments": _redact_json(entry.get("arguments") or {}),
        "result_summary": redact(entry.get("result_summary") or ""),
        "total_tokens": entry.get("total_tokens", 0),
    }


def _one_final(events):
    """Pass events through, ending with exactly one final event.

    Whatever goes wrong upstream, the browser gets a result or an error:
    events after the first final are dropped, and a stream that ends
    without one (or raises) gets the error here. An error never carries
    the exception's text, which can quote paths or prompts.
    """
    try:
        for event in events:
            yield event
            if event.get("type") in FINAL_EVENT_TYPES:
                return
    except Exception as exc:
        log.warning("stream failed: %s", type(exc).__name__)
    yield {"type": "error", "code": "lost", "error": LOST_MESSAGE}


def _waiting_on(events, started):
    """Yield queued events until None, with heartbeats during silence.

    Returns True if STREAM_WATCHDOG_SECONDS passed first, so a stuck worker
    cannot hold the stream open until the platform cuts it.
    """
    while True:
        elapsed = time.monotonic() - started
        left = STREAM_WATCHDOG_SECONDS - elapsed
        if left <= 0:
            return True
        try:
            event = events.get(timeout=min(HEARTBEAT_SECONDS, left))
        except queue.Empty:
            if time.monotonic() - started < STREAM_WATCHDOG_SECONDS:
                yield {"type": "heartbeat",
                       "elapsed_s": int(time.monotonic() - started)}
            continue
        if event is None:
            return False
        yield event


def _iter_replay(store):
    """Stream the saved sample run step by step (no model calls)."""
    sample = _load_sample_memo() or {}
    for entry in sample.get("steps") or []:
        step = _sanitize_step(entry)
        if step is not None:
            yield step
        time.sleep(0.35)
    total = sample.get("total_tokens", 0)
    _record_tokens(store, total)
    yield {"type": "run_result", "reason": "replay",
           "answer": redact(sample.get("memo", "")),
           "total_tokens": total,
           "tool_calls": sample.get("tool_calls", 0),
           "figure_fields": sample.get("figure_fields", [])}


def _iter_live(question, run_id, store):
    """Run the agent in a worker thread, yielding steps as they happen."""
    events = queue.Queue()
    box = {}
    call_log = []
    meter = _TokenMeter(store)

    def on_event(event):
        meter.up_to(event.get("total_tokens"))
        events.put(event)

    def worker():
        try:
            outcome = agent.run_agent(
                question, run_id=run_id, on_event=on_event,
                call_log=call_log)
            meter.up_to(outcome.get("total_tokens"))
            box["outcome"] = outcome
        except SystemExit:
            events.put({"type": "error",
                        "error": "model credentials not configured"})
        except Exception as exc:  # never leak tracebacks or paths
            log.warning("run %s failed: %s", run_id, type(exc).__name__)
            events.put({"type": "error", "error": RUN_FAILED_MESSAGE})
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    started = time.monotonic()
    tokens_so_far = 0
    stream = _waiting_on(events, started)
    while True:
        try:
            event = next(stream)
        except StopIteration as stop:
            timed_out = stop.value
            break
        kind = event.get("type")
        if kind == "error":
            yield {"type": "error", "error": redact(event.get("error") or ""),
                   "total_tokens": tokens_so_far,
                   "model_calls": list(call_log)}
            return
        if kind in ("heartbeat", "model_retry"):
            yield event
            continue
        tokens_so_far = event.get("total_tokens") or tokens_so_far
        step = _sanitize_step(event)
        if step is not None:
            yield step
    if timed_out:
        log.warning("run %s hit the stream watchdog", run_id)
        yield {"type": "run_result", "reason": "took_too_long",
               "answer": agent.TOO_LONG_ANSWER,
               "total_tokens": tokens_so_far,
               "tool_calls": 0, "figure_fields": [],
               "info_request": None, "model_calls": list(call_log)}
        return
    outcome = box.get("outcome")
    if outcome is None:
        return  # _one_final answers for a run that left nothing behind
    total = outcome.get("total_tokens", 0)
    if outcome.get("reason") == "model_failed":
        yield {"type": "error", "code": "model_failed",
               "error": redact(outcome.get("answer", "")),
               "total_tokens": total, "model_calls": list(call_log)}
        return
    yield {"type": "run_result",
           "reason": outcome.get("reason", "done"),
           "answer": redact(outcome.get("answer", "")),
           "total_tokens": total,
           "tool_calls": outcome.get("tool_calls", 0),
           "figure_fields": outcome.get("figure_fields", []),
           "info_request": redact(outcome.get("info_request") or None),
           "model_calls": list(call_log)}


def _iter_info_request(company, period_end, store):
    """Run only the draft_info_request tool, streaming one step."""
    events = queue.Queue()
    box = {}

    def worker():
        try:
            agent.reset_corpus()
            outcome = agent.tool_draft_info_request(
                company, period_end)
            box["outcome"] = outcome
            summary = agent.summarize_result("draft_info_request",
                                             outcome)
            events.put({"run_id": "", "step": 1,
                        "timestamp": _utcnow().isoformat(),
                        "type": "tool_call", "tool": "draft_info_request",
                        "arguments": {"company": company,
                                      "period_end": period_end},
                        "result_summary": summary,
                        "tokens": {"prompt": 0, "completion": 0,
                                   "total": 0},
                        "total_tokens": 0})
        except Exception as exc:  # never leak tracebacks or paths
            events.put({"type": "error",
                        "error": f"{type(exc).__name__}: {exc}"})
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    stream = _waiting_on(events, time.monotonic())
    while True:
        try:
            event = next(stream)
        except StopIteration as stop:
            timed_out = stop.value
            break
        kind = event.get("type")
        if kind == "error":
            yield {"type": "error",
                   "error": redact(event.get("error") or "")}
            return
        if kind == "heartbeat":
            yield event
            continue
        step = _sanitize_step(event)
        if step is not None:
            yield step
    if timed_out:
        yield {"type": "error", "code": "took_too_long",
               "error": REQUEST_TOO_LONG_MESSAGE}
        return
    outcome = box.get("outcome")
    if outcome is None:
        return  # _one_final answers for a run that left nothing behind
    if outcome.get("error"):
        yield {"type": "error",
               "error": redact(outcome.get("error"))}
        return
    _record_tokens(store, 0)
    yield {"type": "run_result", "reason": "info_request",
           "answer": "", "total_tokens": 0, "tool_calls": 1,
           "figure_fields": [],
           "info_request": redact(outcome.get("request") or "")}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health")
def get_health():
    return {"status": "ok"}


@router.get("/samples/memo")
def get_sample_memo():
    sample = _load_sample_memo()
    if sample is None:
        return JSONResponse(status_code=404,
                            content={"detail": "sample memo not found"})
    return sample


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


def _snbr_next_test(period_end):
    """Next-test outlook from the projection file, or None."""
    if not period_end:
        return None
    try:
        projection = _read_json(
            RESULTS_DIR / f"snbr_projection_{period_end}.json")
    except (OSError, ValueError):
        return None
    if not isinstance(projection, dict):
        return None
    onya = (projection.get("projections") or {}).get("onya") or {}
    risk = (projection.get("risk") or {}).get("onya")
    if not projection.get("next_test"):
        return None
    return {"date": projection.get("next_test"),
            "limit": projection.get("next_threshold"),
            "ratio_2dp": onya.get("ratio_2dp"),
            "risk": risk}


def _latest_snbr_result():
    """Newest filed SNBR covenant result, or None when absent."""
    best = None
    for path in RESULTS_DIR.glob("snbr_*.json"):
        if path.name.startswith("snbr_projection_"):
            continue
        try:
            result = _read_json(path)
        except (OSError, ValueError):
            continue
        period = result.get("period_end")
        if period and (best is None or period > best.get("period_end", "")):
            best = result
    return best


def _snbr_company_row(case):
    """Watchlist row from the latest SNBR result (both savings scenarios)."""
    result = _latest_snbr_result()
    if result is None:
        return None
    lev = result.get("net_leverage") or {}
    scenarios = result.get("proforma_scenarios") or []
    with_savings = None
    without_savings = None
    if scenarios:
        high = max(scenarios, key=lambda s: s.get("savings") or 0)
        low = min(scenarios, key=lambda s: s.get("savings") or 0)
        with_savings = (high.get("net_leverage") or {}).get("ratio_2dp")
        if with_savings is None:
            with_savings = (high.get("net_leverage") or {}).get("ratio")
        without_savings = (low.get("net_leverage") or {}).get("ratio_2dp")
        if without_savings is None:
            without_savings = (low.get("net_leverage") or {}).get("ratio")
    ratio = without_savings if without_savings is not None else lev.get("ratio")
    threshold = lev.get("threshold")
    headroom = (threshold - ratio
                if threshold is not None and ratio is not None else None)
    # Breach when even the maximum-savings scenario fails; fail on the
    # conservative (no-savings) ratio otherwise.
    best_pass = None
    if scenarios:
        best_pass = max(
            scenarios, key=lambda s: s.get("savings") or 0
        ).get("net_leverage", {}).get("pass")
    if best_pass is False:
        status = "fail"
    elif ratio is not None and threshold is not None:
        status = "pass" if ratio <= threshold else "fail"
    elif lev.get("pass") is True:
        status = "pass"
    elif lev.get("pass") is False:
        status = "fail"
    else:
        status = "unknown"
    period_end = result.get("period_end")
    next_test = _snbr_next_test(period_end)
    return {
        "ticker": "SNBR",
        "name": clean_company_name("SNBR", company_name(case)),
        "period_end": period_end,
        "as_of": period_end,
        "next_test": next_test,
        "covenant": "Net leverage",
        "ratio": ratio,
        "threshold": threshold,
        "headroom": headroom,
        "status": status,
        "scenarios": scenarios or None,
        "ratio_with_savings": with_savings,
        "ratio_without_savings": without_savings,
    }


@router.get("/companies")
def list_companies():
    cases = _read_json(BACKTEST_DIR / "companies.json")
    companies = []
    for case in cases:
        ticker = case["ticker"]
        if ticker.upper() == "SNBR":
            row = _snbr_company_row(case)
            if row is not None:
                companies.append(row)
                continue
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
        period_end = (disclosed or {}).get("period_end") or case.get("period_end")
        companies.append({
            "ticker": ticker,
            "name": clean_company_name(ticker, company_name(case)),
            "period_end": period_end,
            "as_of": period_end,
            "covenant": normalize_covenant_name((primary or {}).get("name")),
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
    body["covenant_clause"] = _net_leverage_clause(result)
    return body


def _net_leverage_clause(result):
    """Net Leverage covenant clause (section 5.7(a)) for the evidence margin."""
    try:
        contract = _read_json(EXTRACTED_DIR / "snbr_covenants.reviewed.json")
    except (OSError, ValueError):
        return None
    for cov in contract.get("financial_covenants", []) or []:
        if cov.get("name") == "Net Leverage Ratio":
            lev = result.get("net_leverage") or {}
            return {
                "name": cov.get("name"),
                "section": cov.get("section"),
                "quote": cov.get("quote"),
                "threshold": lev.get("threshold"),
                "period_end": result.get("period_end"),
            }
    return None


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


def _cap_evidence(clause_refs):
    """Shared cap clause covering all clause_refs, or None."""
    try:
        contract = _read_json(EXTRACTED_DIR / "snbr_covenants.reviewed.json")
    except (OSError, ValueError):
        return None
    wanted = set(clause_refs)
    for group in contract.get("cap_groups", []) or []:
        if wanted and wanted <= set(group.get("applies_to_clauses", [])):
            return {
                "applies_to_clauses": group.get("applies_to_clauses"),
                "quote": group.get("quote"),
                "schedule": group.get("schedule"),
            }
    return None


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
        return {"ref": ref, "kind": "contract", "clauses": clauses,
                "cap": _cap_evidence(clause_refs)}
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
            if cov.get("paired_by_direction"):
                term_notes.append(
                    f"{ticker} {cov.get('name')} is paired with the disclosed "
                    f"{cov.get('disclosed_name')} by direction, because the "
                    "agreement and the filing name it differently.")
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
                      "records": records, "notes": term_notes},
            "recompute": _recompute_section(cases)}


def _recompute_section(cases):
    """XBRL recomputation results, reported apart from the headline totals."""
    rows = []
    companies = set()
    notes = []
    for case in cases:
        ticker = case["ticker"]
        if ticker.upper() == "SNBR":
            continue
        try:
            record = _read_json(
                _data_file("backtest", f"recompute_{ticker}.json"))
        except (OSError, ValueError):
            notes.append(f"{ticker} was not recomputed, because no agreement "
                         "text was read.")
            continue
        for ratio in record.get("ratios", []) or []:
            companies.add(ticker)
            rows.append({"ticker": ticker,
                         **{k: ratio.get(k) for k in (
                             "name", "disclosed_name", "recomputed",
                             "disclosed", "difference", "status", "missing")}})
    return {
        "rows": rows,
        "totals": {
            "ratios": len(rows),
            "companies": len(companies),
            "full": sum(1 for r in rows if r["status"] == "match"),
            "partial": sum(1 for r in rows if r["status"] == "partial"),
            "mismatched": sum(1 for r in rows if r["status"] == "mismatch"),
            "numeric": sum(1 for r in rows if r["recomputed"] is not None),
        },
        "notes": notes,
    }


class RunRequest(BaseModel):
    question: str


@router.post("/agent/run")
def stream_agent_run(body: RunRequest, request: Request,
                     x_onya_token: str | None = Header(default=None)):
    """Validate, then stream the run as newline-delimited JSON events."""
    expected = _expected_token()
    if not expected:
        return JSONResponse(status_code=500,
                            content={"detail": "server token not configured"})
    if not secrets.compare_digest(x_onya_token or "", expected):
        return JSONResponse(status_code=401,
                            content={"detail": "invalid token"})
    if not _agent_enabled():
        return _paused()
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
    try:
        store = limits.resolve_store()
    except limits.RedisUnavailable:
        return _paused()
    ip = _client_ip(request, token_valid=True)
    claimed = _claim_limits(store, ip)
    if claimed is not None:
        return claimed
    if _budget_exhausted(store):
        return JSONResponse(
            status_code=429,
            content={"detail": "The daily token budget is used up for today."})
    run_id = uuid.uuid4().hex[:12]

    def events():
        if _agent_replay_enabled():
            yield from _iter_replay(store)
        else:
            yield from _iter_live(question, run_id, store)

    def body_lines():
        for event in _one_final(events()):
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(body_lines(),
                             media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store"})


@router.get("/agent/run/{run_id}")
def get_agent_run(run_id: str):
    return JSONResponse(
        status_code=404,
        content={"detail": "run polling was removed; "
                           "POST /agent/run streams the run"})


def _offline_cik(ticker):
    """CIK with no network: digits or the local registry, else None."""
    import edgar

    s = str(ticker or "").strip()
    if s.isdigit():
        try:
            return edgar._cik_10(s)
        except ValueError:
            return None
    try:
        registry = _read_json(DATA_DIR / "companies.json")
    except (OSError, ValueError):
        return None
    info = (registry or {}).get(s.upper())
    if isinstance(info, dict) and info.get("cik"):
        try:
            return edgar._cik_10(info["cik"])
        except ValueError:
            return None
    return None


@router.get("/company/{ticker}/filings-since")
def get_filings_since(ticker: str, date: str = Query(default="")):
    """10-K/10-Q/8-K filings after date, from the cached submissions.

    Never calls EDGAR: when the submissions cache is missing the
    answer says so instead.
    """
    import edgar

    day = (date or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return JSONResponse(status_code=422,
                            content={"detail": "date=YYYY-MM-DD is required"})
    cik = _offline_cik(ticker)
    if cik is None:
        return JSONResponse(status_code=404,
                            content={"detail": "unknown company"})
    rows = edgar.filings_since(cik, day)
    if rows is None:
        return {"ticker": str(ticker).upper(), "date": day,
                "cached": False, "filings": [],
                "note": ("submissions cache is missing for this company; "
                         "no live lookup was attempted")}
    return {"ticker": str(ticker).upper(), "date": day,
            "cached": True, "filings": rows,
            "checked_through": edgar.filings_checked_through(cik)}


class InfoRequestBody(BaseModel):
    company: str = ""
    period_end: str = ""


@router.post("/agent/info-request")
def stream_info_request(body: InfoRequestBody, request: Request,
                        x_onya_token: str | None = Header(default=None)):
    """Run only draft_info_request, streamed, counted in limits."""
    expected = _expected_token()
    if not expected:
        return JSONResponse(status_code=500,
                            content={"detail": "server token not configured"})
    if not secrets.compare_digest(x_onya_token or "", expected):
        return JSONResponse(status_code=401,
                            content={"detail": "invalid token"})
    if not _agent_enabled():
        return _paused()
    company = (body.company or "").strip()
    period_end = (body.period_end or "").strip()
    if not company or not period_end:
        return JSONResponse(status_code=422,
                            content={"detail": "company and period_end "
                                               "are required"})
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_end):
        return JSONResponse(status_code=422,
                            content={"detail": "period_end must be "
                                               "YYYY-MM-DD"})
    try:
        store = limits.resolve_store()
    except limits.RedisUnavailable:
        return _paused()
    ip = _client_ip(request, token_valid=True)
    claimed = _claim_limits(store, ip)
    if claimed is not None:
        return claimed
    if _budget_exhausted(store):
        return JSONResponse(
            status_code=429,
            content={"detail": "The daily token budget is used up for today."})

    def body_lines():
        for event in _one_final(
                _iter_info_request(company, period_end, store)):
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(body_lines(),
                             media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store"})


class CompareBody(BaseModel):
    ticker: str = ""
    period_end: str = ""
    text: str | None = None
    file_b64: str | None = None
    filename: str | None = None


def _private_replay_figures():
    """Saved extraction for tests, or None outside replay mode."""
    if os.environ.get("ONYA_PRIVATE_REPLAY") != "1":
        return None
    try:
        saved = _read_json(
            _data_file("samples", "private_compare_replay.json"))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or "figures" not in saved:
        return None
    return saved


def _iter_private_compare(ticker, period_end, text, file_b64, filename,
                          store):
    """Stream progress events, then the comparison result."""
    import model_calls
    import private_compare

    events = queue.Queue()
    box = {}
    call_log = []

    def worker():
        try:
            replay = _private_replay_figures()
            events.put({"type": "progress", "step": "reading upload"})
            events.put({"type": "progress", "step": "extracting figures"})
            if replay is not None:
                figures = replay["figures"]
                tokens = 0
                result = private_compare.compare_with_onya(
                    ticker, period_end, figures)
                result["figures"] = figures
            else:
                result, tokens, _timings = private_compare.run_compare(
                    ticker, period_end, text=text, file_b64=file_b64,
                    filename=filename, on_retry=events.put,
                    call_log=call_log)
            _record_tokens(store, tokens)  # here, in case the stream is gone
            box["result"] = result
            box["tokens"] = tokens
        except private_compare.PrivateUnavailable as exc:
            events.put({"type": "error", "code": "unavailable",
                        "error": str(exc)})
        except private_compare.PrivateInputError as exc:
            events.put({"type": "error", "error": str(exc)})
        except model_calls.ModelCallFailed:
            events.put({"type": "error", "code": "model_failed",
                        "error": PRIVATE_MODEL_FAILED_MESSAGE})
        except Exception:  # never leak tracebacks, paths, or content
            events.put({"type": "error",
                        "error": "comparison failed"})
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    stream = _waiting_on(events, time.monotonic())
    while True:
        try:
            event = next(stream)
        except StopIteration as stop:
            timed_out = stop.value
            break
        if event.get("type") == "error":
            yield {**event, "model_calls": list(call_log)}
            return
        yield event
    if timed_out:
        yield {"type": "error", "code": "took_too_long",
               "error": PRIVATE_TOO_LONG_MESSAGE,
               "model_calls": list(call_log)}
        return
    result = box.get("result")
    if result is None:
        return  # _one_final answers for a run that left nothing behind
    yield {"type": "private_result", "reason": "private_compare",
           "total_tokens": box.get("tokens") or 0,
           "comparison": _redact_json(result),
           "model_calls": list(call_log)}


@router.post("/private/compare")
def stream_private_compare(body: CompareBody, request: Request,
                           x_onya_token: str | None = Header(default=None)):
    """Compare a certificate with Onya, streamed, counted in limits."""
    expected = _expected_token()
    if not expected:
        return JSONResponse(status_code=500,
                            content={"detail": "server token not configured"})
    if not secrets.compare_digest(x_onya_token or "", expected):
        return JSONResponse(status_code=401,
                            content={"detail": "invalid token"})
    import private_compare

    if os.environ.get("ONYA_PRIVATE_REPLAY") != "1":
        try:
            private_compare.make_baseten_client().close()
        except private_compare.PrivateUnavailable as exc:
            return JSONResponse(status_code=503,
                                content={"detail": str(exc)})
        except Exception:
            pass
    ticker = (body.ticker or "").strip()
    period_end = (body.period_end or "").strip()
    if not ticker or not period_end:
        return JSONResponse(status_code=422,
                            content={"detail": "ticker and period_end "
                                               "are required"})
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_end):
        return JSONResponse(status_code=422,
                            content={"detail": "period_end must be "
                                               "YYYY-MM-DD"})
    if not body.text and not body.file_b64:
        return JSONResponse(status_code=422,
                            content={"detail": "pasted text or a file "
                                               "is required"})
    try:
        store = limits.resolve_store()
    except limits.RedisUnavailable:
        return _paused()
    ip = _client_ip(request, token_valid=True)
    claimed = _claim_limits(store, ip)
    if claimed is not None:
        return claimed
    if _budget_exhausted(store):
        return JSONResponse(
            status_code=429,
            content={"detail": "The daily token budget is used up for today."})

    def body_lines():
        for event in _one_final(_iter_private_compare(
                ticker, period_end, body.text, body.file_b64,
                body.filename, store)):
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(body_lines(),
                             media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store"})


@router.get("/private/sample")
def get_private_sample():
    """The illustrative sample certificate text (public demo data)."""
    import private_compare

    try:
        text = (_data_file("samples", private_compare.SAMPLE_NAME)
                .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return JSONResponse(status_code=404,
                            content={"detail": "sample not found"})
    return {"filename": private_compare.SAMPLE_NAME, "text": text}


def allowed_origins():
    if _is_production():
        origin = (os.environ.get("ONYA_FRONTEND_ORIGIN") or "").strip()
        return [origin] if origin else []
    origins = [LOCAL_ORIGIN]
    extra = (os.environ.get("ONYA_FRONTEND_ORIGIN") or "").strip()
    if extra and extra not in origins:
        origins.append(extra)
    return origins


def create_app():
    if _is_production():
        if "ONYA_AGENT_REPLAY" in os.environ:
            raise RuntimeError(
                "ONYA_AGENT_REPLAY must not be set in production")
        if not (os.environ.get("ONYA_DEMO_TOKEN") or "").strip():
            raise RuntimeError(
                "ONYA_DEMO_TOKEN is required in production")
        if not (os.environ.get("ONYA_FRONTEND_ORIGIN") or "").strip():
            raise RuntimeError(
                "ONYA_FRONTEND_ORIGIN is required in production")
    app = FastAPI(title="Onya demo API")

    @app.middleware("http")
    async def _cache_headers(request, call_next):
        response = await call_next(request)
        if (request.method == "GET"
                and not request.url.path.startswith("/agent")):
            response.headers.setdefault(
                "Cache-Control", "public, max-age=60")
        return response
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
