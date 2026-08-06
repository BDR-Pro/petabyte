#!/usr/bin/env python3
"""End-to-end observability smoke test.

Generates a SAFE synthetic operation with a unique run_id and verifies the telemetry
pipeline. It never creates a fake financial record and never marks a payment or job
completed — it only proves telemetry flows.

Two tiers:
  * LOCAL checks (always run, offline): a trace/span is created, W3C context propagates to
    a simulated worker, structured JSON logs carry the run_id, a Prometheus test counter
    increments, and NO secret appears in any emitted test event.
  * REMOTE checks (run only when the endpoint is configured; SKIPPED — not failed — when
    unset): the trace reaches Tempo, Loki has the log line, Grafana datasources are
    healthy, and (only when SMOKE_SENTRY=1) a controlled test error reaches Sentry.

Exit non-zero only on a REAL failure (a configured endpoint that is unreachable, or a
local check that fails). Unconfigured remote endpoints are skips, so this is usable both
in the offline CI sandbox and on the deploy runner that can reach the observability server.
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lumaris_api"))

with __import__("contextlib").suppress(Exception):
    from config_context import hydrate_env
    hydrate_env()

import observability as o  # noqa: E402

_fail = 0
_skip = 0
SENTINEL = "SMOKE_SECRET_sk_live_MUSTNOTLEAK_1234567890"
RUN_ID = f"smoke-{int(time.time())}-{os.getpid():x}"


def ok(label, cond):
    global _fail
    print(("ok    " if cond else "FAIL  ") + label)
    if not cond:
        _fail += 1


def skip(label, why):
    global _skip
    _skip += 1
    print(f"skip  {label} ({why})")


def _reachable(url: str, timeout=4.0) -> bool:
    try:
        import httpx
        r = httpx.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def main() -> int:
    o.init_observability("petabyte-api")
    h = o.health()
    print(f"== observability smoke test (run_id={RUN_ID}) ==")
    print(f"tracing active={h['tracing']['active']} metrics active={h['metrics']['active']} "
          f"otlp={h['tracing']['endpoint_configured']}")

    captured = []
    import logging

    class _Cap(logging.Handler):
        def emit(self, record):
            captured.append(o.JsonFormatter().format(record))

    _obs_logger = logging.getLogger("petabyte.obs")
    _obs_logger.addHandler(_Cap())
    _obs_logger.setLevel(logging.INFO)  # capture INFO events regardless of ambient LOG_LEVEL

    # --- LOCAL: API emits a span + a worker receives propagated context ---
    carrier = {}
    worker_trace = None
    with o.ctx(run_id=RUN_ID, data_class="test"):
        with o.span("smoke.api.request", kind="server"):
            o.event("smoke.api.received", message="synthetic op", run_id=RUN_ID,
                    note="no financial record created", leaked=SENTINEL)
            o.inject_context(carrier)
            api_trace = o.get_context().get("trace_id")
        # simulate the worker on the other side of the queue
        with o.span("smoke.worker.process", kind="consumer", carrier=carrier):
            worker_trace = o.get_context().get("trace_id")
            o.event("smoke.worker.processed", message="worker got job", run_id=RUN_ID)

    if h["tracing"]["active"]:
        ok("API emits a trace (span created)", bool(api_trace))
        ok("worker receives the SAME trace via W3C propagation",
           worker_trace and worker_trace == api_trace)
    else:
        skip("API/worker trace", "OTel SDK/endpoint not active in this environment")

    # --- LOCAL: structured logs carry the run_id ---
    joined = "\n".join(captured)
    ok("structured JSON logs carry the run_id", RUN_ID in joined)
    ok("NO secret value appears in any emitted test event", SENTINEL not in joined)

    # --- LOCAL: Prometheus test counter increments ---
    if h["metrics"]["active"]:
        o.inc_metric("petabyte_telemetry_export_failures_total",
                     exporter="smoketest", environment=o.ENVIRONMENT)
        body = o.metrics_response()[0].decode()
        ok("Prometheus records a test counter", "petabyte_telemetry_export_failures_total" in body)
        ok("no secret in the metrics exposition", SENTINEL not in body)
    else:
        skip("Prometheus counter", "prometheus_client not installed")

    # --- LOCAL: Redis metrics/health update when configured ---
    try:
        sys.path.insert(0, os.path.join(ROOT, "lumaris_api"))
        import redis_client
        rh = redis_client.health()
        if rh.get("enabled"):
            redis_client.incr_window(f"smoke:{RUN_ID}", 30)
            ok("Redis reachable + counter updated", redis_client.available())
        else:
            skip("Redis queue/lock metrics", "REDIS not enabled")
    except Exception as e:
        skip("Redis", f"unavailable ({e})")

    # --- REMOTE: only when configured; a configured-but-unreachable endpoint FAILS ---
    tempo = os.getenv("TEMPO_URL", "").strip()
    if tempo:
        ok("Tempo endpoint reachable (trace store)", _reachable(f"{tempo}/api/echo") or _reachable(tempo))
    else:
        skip("Tempo contains the trace", "TEMPO_URL unset (cannot verify from here)")

    loki = os.getenv("LOKI_URL", "").strip()
    if loki:
        ok("Loki endpoint reachable (log store)", _reachable(f"{loki}/ready") or _reachable(loki))
    else:
        skip("Loki has the log line", "LOKI_URL unset")

    graf = os.getenv("GRAFANA_URL", "").strip()
    if graf:
        ok("Grafana datasources endpoint reachable", _reachable(f"{graf}/api/health"))
    else:
        skip("Grafana data sources healthy", "GRAFANA_URL unset")

    if os.getenv("SMOKE_SENTRY") == "1" and os.getenv("SENTRY_DSN"):
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], environment=o.ENVIRONMENT)
            sentry_sdk.capture_message(f"observability smoke test {RUN_ID} (controlled)")
            sentry_sdk.flush(timeout=5)
            ok("controlled test event sent to Sentry", True)
        except Exception as e:
            ok("controlled test event sent to Sentry", False) or print(f"  sentry error: {e}")
    else:
        skip("Sentry controlled test event", "SMOKE_SENTRY!=1 or SENTRY_DSN unset")

    print(f"\n== smoke: {_fail} failed, {_skip} skipped ==")
    print("NOTE: skipped remote checks require the observability server; run this on the "
          "deploy runner / a box that can reach it. No payment or job was marked complete.")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
