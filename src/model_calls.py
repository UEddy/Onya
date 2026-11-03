"""Bounded, logged model calls for the request paths.

The SDK's own retries are switched off (max_retries=0 on the clients), so
a stuck call cannot wait in silence past the run's deadline. Each attempt
gets a wall-clock limit that fits inside the time left, at most one retry
is made, and the retry is reported through on_retry so the page can say so.

Logs carry only labels, durations, outcomes, and token counts: never
prompt text, model output, or exception messages, which can quote either.
"""

import json
import logging
import os
import sys
import threading
import time

import openai

PER_CALL_SECONDS = 90  # the slowest healthy call observed took about 53 s
MIN_CALL_SECONDS = 10  # with less time left, stop rather than start a call
MIN_RETRY_SECONDS = 20  # a retry must have time to finish
DEADLINE_MARGIN_SECONDS = 3  # a call ends before the deadline, not at it

log = logging.getLogger("onya.model")
if os.environ.get("ONYA_ENV") == "production" and not log.handlers:
    # Only this logger: its lines are content-free by construction.
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class Deadline:
    """Time left for a whole run, measured from its creation."""

    def __init__(self, seconds):
        self.ends_at = time.monotonic() + seconds

    def remaining(self):
        return self.ends_at - time.monotonic()


class ModelCallFailed(Exception):
    """A model call failed for good. The text is safe to show."""

    def __init__(self, label, outcome, attempts):
        super().__init__(f"{label} failed: {outcome} after "
                         f"{attempts} attempt(s)")
        self.label = label
        self.outcome = outcome
        self.attempts = attempts


class DeadlineReached(ModelCallFailed):
    """Too little of the run's deadline is left to start a call."""


class _WallClockTimeout(Exception):
    """The SDK's timeout covers gaps between bytes; this covers the call."""


def _with_wall_clock(func, seconds):
    box = {}
    done = threading.Event()

    def work():
        try:
            box["value"] = func()
        except BaseException as exc:  # handed to the waiting thread
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    if not done.wait(seconds):
        raise _WallClockTimeout()
    if "error" in box:
        raise box["error"]
    return box["value"]


def _classify(exc):
    """(outcome, retryable), never using the exception's message."""
    if isinstance(exc, (_WallClockTimeout, openai.APITimeoutError)):
        return "timeout", True
    if isinstance(exc, openai.APIConnectionError):
        return "connection_error", True
    if isinstance(exc, openai.RateLimitError):
        return "rate_limited", True
    if isinstance(exc, openai.InternalServerError):
        return "server_error", True
    if isinstance(exc, openai.APIStatusError):
        return f"rejected_{exc.status_code}", False
    return f"error_{type(exc).__name__}", False


def _log_line(**fields):
    log.info(json.dumps({"event": "model_call", **fields}))


def call(client, *, label, deadline, run_id="", call_log=None, on_retry=None,
         max_retries=1, per_call_s=PER_CALL_SECONDS, **request):
    """One chat completion, bounded by deadline; raises ModelCallFailed.

    Retries once on a timeout, connection error, rate limit, or server
    error, and only when deadline still leaves room to finish.
    """
    attempt = 0
    while True:
        attempt += 1
        remaining = deadline.remaining()
        if remaining < MIN_CALL_SECONDS:
            _log_line(phase="skipped", label=label, run_id=run_id,
                      attempt=attempt, outcome="deadline",
                      remaining_s=round(remaining, 1))
            raise DeadlineReached(label, "deadline", attempt - 1)
        limit = min(per_call_s, remaining - DEADLINE_MARGIN_SECONDS)
        _log_line(phase="start", label=label, run_id=run_id, attempt=attempt,
                  limit_s=round(limit, 1))
        started = time.monotonic()
        failure = None
        try:
            response = _with_wall_clock(
                lambda: client.chat.completions.create(
                    timeout=limit, **request), limit)
        except Exception as exc:
            failure = exc
        duration = round(time.monotonic() - started, 2)
        if failure is None:
            usage = getattr(response, "usage", None)
            tokens = getattr(usage, "total_tokens", 0) or 0
            _log_line(phase="end", label=label, run_id=run_id,
                      attempt=attempt, duration_s=duration, outcome="ok",
                      tokens=tokens)
            if call_log is not None:
                call_log.append({"label": label, "attempt": attempt,
                                 "duration_s": duration, "outcome": "ok"})
            return response
        outcome, retryable = _classify(failure)
        _log_line(phase="end", label=label, run_id=run_id, attempt=attempt,
                  duration_s=duration, outcome=outcome)
        if call_log is not None:
            call_log.append({"label": label, "attempt": attempt,
                             "duration_s": duration, "outcome": outcome})
        if (not retryable or attempt > max_retries
                or deadline.remaining() < MIN_RETRY_SECONDS):
            raise ModelCallFailed(label, outcome, attempt) from None
        if on_retry is not None:
            on_retry({"type": "model_retry", "label": label,
                      "attempt": attempt + 1, "reason": outcome})
