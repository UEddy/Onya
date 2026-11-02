"""Persistent agent limits on Redis (Upstash REST), memory locally.

Rate limits (5 runs/hour/visitor, 30/day total) and the daily token
budget must survive across serverless instances, so in production they
live in Redis through the Upstash REST client. Every counter uses one
atomic Lua increment that sets its expiry on first touch.

Locally (no Redis configured, not production) an in-memory store keeps
the existing behavior for development and tests. In production, a
missing or unreachable Redis fails closed: callers get RedisUnavailable
and must refuse the run, never run unlimited.
"""

import os
import threading

try:
    from upstash_redis import Redis as _UpstashRedis
except ImportError:  # pragma: no cover - client is a real dependency
    _UpstashRedis = None

MAX_RUNS_PER_HOUR_PER_IP = 5
MAX_RUNS_PER_DAY_TOTAL = 30

_CLAIM_SCRIPT = (
    "local current = redis.call('INCR', KEYS[1]); "
    "if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
    "return current;"
)


class RedisUnavailable(Exception):
    """Redis is required (production) but missing or unreachable."""


def _is_production():
    return (os.environ.get("ONYA_ENV") or "") == "production"


def _day():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat()


def _hour():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")


class MemoryStore:
    """Thread-safe in-memory counters (local dev and tests only)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {}

    def claim(self, key, ttl_seconds):
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

    def add(self, key, amount, ttl_seconds):
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + amount
            return self._counts[key]

    def total(self, key):
        with self._lock:
            return self._counts.get(key, 0)

    def reset(self):
        with self._lock:
            self._counts.clear()


class UpstashStore:
    """Atomic counters over the Upstash REST client."""

    def __init__(self, client):
        self._client = client

    def _eval_claim(self, key, ttl_seconds, amount):
        script = _CLAIM_SCRIPT
        if amount != 1:
            script = (
                "local current = redis.call('INCRBY', KEYS[1], ARGV[2]); "
                "if current == tonumber(ARGV[2]) then "
                "redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
                "return current;"
            )
        try:
            result = self._client.eval(
                script, keys=[key], args=[ttl_seconds, amount])
        except Exception as exc:
            raise RedisUnavailable(f"redis unreachable: {exc}") from exc
        return int(result)

    def claim(self, key, ttl_seconds):
        return self._eval_claim(key, int(ttl_seconds), 1)

    def add(self, key, amount, ttl_seconds):
        try:
            amount = int(amount or 0)
        except (TypeError, ValueError):
            return 0
        if amount <= 0:
            return self.total(key)
        return self._eval_claim(key, int(ttl_seconds), amount)

    def total(self, key):
        try:
            value = self._client.get(key)
        except Exception as exc:
            raise RedisUnavailable(f"redis unreachable: {exc}") from exc
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0


_LOCAL_STORE = None
_LOCAL_LOCK = threading.Lock()


def local_store():
    """Process-wide memory store (local dev and tests only)."""
    global _LOCAL_STORE
    with _LOCAL_LOCK:
        if _LOCAL_STORE is None:
            _LOCAL_STORE = MemoryStore()
        return _LOCAL_STORE


def reset_local():
    """Clear the process-wide memory store (tests only)."""
    global _LOCAL_STORE
    with _LOCAL_LOCK:
        _LOCAL_STORE = None


def resolve_store():
    """Upstash when configured, shared memory locally, fail closed."""
    url = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").strip()
    token = (os.environ.get("UPSTASH_REDIS_REST_TOKEN") or "").strip()
    if url and token:
        if _UpstashRedis is None:
            if _is_production():
                raise RedisUnavailable("upstash-redis client not installed")
            return local_store()
        try:
            client = _UpstashRedis(url=url, token=token)
        except Exception as exc:
            raise RedisUnavailable(f"redis unreachable: {exc}") from exc
        return UpstashStore(client)
    if _is_production():
        raise RedisUnavailable("redis is not configured in production")
    return local_store()


def ip_key(ip):
    return f"onya:runs:ip:{ip}:{_hour()}"


def day_key():
    return f"onya:runs:day:{_day()}"


def tokens_key():
    return f"onya:tokens:{_day()}"
