"""Optional, instrumented Redis client for Petabyte.

Redis is a COORDINATION cache, never the ledger. It is used (when configured) for rate
limiting, idempotency coordination, distributed reservation locks, quote caching and
job-status fanout. Money/audit/ledger state always lives in Postgres.

Everything here is degrade-safe: if the `redis` library is absent, REDIS_URL is unset,
REDIS_ENABLED=false, or Redis is unreachable, every call returns a neutral value and the
caller falls back to its in-process behaviour. A circuit breaker stops hammering a dead
Redis and emits a single `redis.unavailable` event. All ops are traced + metered with
bounded-cardinality labels and never carry sensitive cached values into telemetry.
"""
from __future__ import annotations

import os
import time

import observability as _obs

_NAMESPACE = os.getenv("REDIS_NAMESPACE", "petabyte")
_URL = os.getenv("REDIS_URL", "").strip()
_ENABLED = os.getenv("REDIS_ENABLED", "false").strip().lower() == "true" and bool(_URL)
_CONNECT_TIMEOUT = _obs._f("REDIS_CONNECT_TIMEOUT_S", 2.0)
_OP_TIMEOUT = _obs._f("REDIS_OP_TIMEOUT_S", 2.0)
_BREAKER_THRESHOLD = _obs._i("REDIS_BREAKER_THRESHOLD", 5)
_BREAKER_COOLDOWN_S = _obs._f("REDIS_BREAKER_COOLDOWN_S", 30.0)

_client = None
_init_tried = False
_consec_failures = 0
_open_until = 0.0

# Lua: release a lock only if we still own it (compare token, then delete). Atomic.
_UNLOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""


def _key(*parts: str) -> str:
    return ":".join((_NAMESPACE, *[str(p) for p in parts]))


def available() -> bool:
    """True if Redis is configured, importable, and the breaker is closed."""
    return _ENABLED and _get_client() is not None and time.time() >= _open_until


def _breaker_open() -> bool:
    return time.time() < _open_until


def _record_failure(op: str, err: Exception) -> None:
    global _consec_failures, _open_until
    _consec_failures += 1
    _obs.inc_metric("petabyte_telemetry_export_failures_total",
                    exporter="redis", environment=_obs.ENVIRONMENT)
    if _consec_failures >= _BREAKER_THRESHOLD and not _breaker_open():
        _open_until = time.time() + _BREAKER_COOLDOWN_S
        _obs.event(_obs.EVENTS.REDIS_UNAVAILABLE, message="redis circuit opened",
                   op=op, cooldown_s=_BREAKER_COOLDOWN_S, reason=str(err)[:120])


def _record_success() -> None:
    global _consec_failures
    _consec_failures = 0


def _get_client():
    global _client, _init_tried
    if not _ENABLED:
        return None
    if _client is not None:
        return _client
    if _init_tried:
        return _client
    _init_tried = True
    try:
        import redis  # noqa: F401
        from redis import Redis
        _client = Redis.from_url(
            _URL, password=os.getenv("REDIS_PASSWORD") or None,
            socket_connect_timeout=_CONNECT_TIMEOUT, socket_timeout=_OP_TIMEOUT,
            retry_on_timeout=False, decode_responses=True,
        )
    except Exception as e:  # noqa: BLE001
        _obs.event(_obs.EVENTS.REDIS_UNAVAILABLE, message="redis client init failed",
                   reason=str(e)[:120])
        _client = None
    return _client


def _do(op: str, fn, default):
    """Run a Redis op with tracing, metrics, timeout, and breaker. Returns `default` on any
    failure or when Redis is unavailable (caller falls back)."""
    if not _ENABLED or _breaker_open():
        return default
    cli = _get_client()
    if cli is None:
        return default
    t0 = time.time()
    try:
        with _obs.span(f"redis.{op}", kind="client", **{"db.system": "redis"}):
            result = fn(cli)
        _record_success()
        return result
    except Exception as e:  # noqa: BLE001 — Redis must never break the caller
        _record_failure(op, e)
        return default


# --------------------------------------------------------------------------- primitives
def cache_get(key: str):
    return _do("get", lambda c: c.get(_key(key)), None)


def cache_set(key: str, value: str, ttl_s: int) -> bool:
    return bool(_do("set", lambda c: c.set(_key(key), value, ex=max(1, int(ttl_s))), False))


def incr_window(key: str, window_s: int) -> int | None:
    """Atomic counter with a TTL — the primitive behind a Redis rate limiter. Returns the
    new count, or None if Redis is unavailable (caller uses its in-process limiter)."""
    def _fn(c):
        pipe = c.pipeline()
        k = _key("rl", key)
        pipe.incr(k)
        pipe.expire(k, max(1, int(window_s)))
        return pipe.execute()[0]
    return _do("incr", _fn, None)


def read_window(key: str) -> int | None:
    """Current value of a window counter written by incr_window(). None if unavailable."""
    v = _do("get", lambda c: c.get(_key("rl", key)), None)
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def acquire_lock(name: str, token: str, ttl_ms: int) -> bool:
    """SET NX PX — a single-holder distributed lock. `token` must be unique per caller so
    only the owner can release it."""
    ok = _do("lock", lambda c: c.set(_key("lock", name), token, nx=True, px=max(1, int(ttl_ms))),
             None)
    if ok:
        _obs.event(_obs.EVENTS.LOCK_ACQUIRED, message="lock acquired", lock=name)
        return True
    if ok is False:
        _obs.event(_obs.EVENTS.LOCK_CONFLICT, message="lock busy", lock=name)
    return False


def release_lock(name: str, token: str) -> bool:
    """Release the lock only if we still own it (atomic compare-and-delete)."""
    return bool(_do("unlock",
                    lambda c: c.eval(_UNLOCK_LUA, 1, _key("lock", name), token), 0))


def mark_idempotent(key: str, ttl_s: int) -> bool:
    """Claim an idempotency slot: True the FIRST time, False if already claimed. Redis
    unavailable -> True (caller falls back to its DB-backed idempotency)."""
    res = _do("idem", lambda c: c.set(_key("idem", key), "1", nx=True, ex=max(1, int(ttl_s))),
              None)
    return True if res is None else bool(res)


def health() -> dict:
    """Redis integration health (for /health/observability and the smoke test)."""
    h = {"configured": bool(_URL), "enabled": _ENABLED, "breaker_open": _breaker_open(),
         "consecutive_failures": _consec_failures}
    if _ENABLED and not _breaker_open():
        h["ping"] = bool(_do("ping", lambda c: c.ping(), False))
    return h
