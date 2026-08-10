"""Offline tests for the observability layer (correlation, redaction, bounded-cardinality
metrics, degrade-safety, secret hygiene, and access control). No collector needed — OTel
is pointed at a bogus endpoint so spans are created locally and export failures are
swallowed (proving telemetry never breaks the caller).

Run: python observability_test.py
"""
import json
import logging
import os

# Configure BEFORE importing observability so module-level config picks it up.
os.environ["OBSERVABILITY_ENABLED"] = "true"
os.environ["OTEL_ENABLED"] = "true"
os.environ["PROMETHEUS_ENABLED"] = "true"
os.environ["LOG_FORMAT"] = "json"
os.environ["LOG_REDACTION_ENABLED"] = "true"
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:4317"  # unreachable on purpose
os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
os.environ["ENVIRONMENT"] = "test"

import observability as o  # noqa: E402

o.init_observability("petabyte-api")
# The log-capture checks below need INFO records regardless of the ambient LOG_LEVEL
# (the suite may run with LOG_LEVEL=warning). Force this test's logger to INFO.
logging.getLogger("petabyte.obs").setLevel(logging.INFO)

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---- correlation context generated + propagated ----
rid = o.new_request_id()
ok("request_id is generated (hex, >=8 chars)", isinstance(rid, str) and len(rid) >= 8)
ok("a bad incoming request id is rejected", o.sanitize_incoming_request_id("bad id!") is None)
ok("a safe incoming request id is accepted",
   o.sanitize_incoming_request_id("abc-123.def_456") == "abc-123.def_456")

with o.ctx(transaction_id="tx_pub_1", job_id="job_9", buyer_id="42"):
    c = o.get_context()
    ok("context carries the correlation ids", c.get("transaction_id") == "tx_pub_1"
       and c.get("job_id") == "job_9")
ok("context is restored after the scope exits", "transaction_id" not in o.get_context())

# ---- W3C trace context: a span sets trace_id/span_id into the context ----
otel_active = o.health()["tracing"]["active"]
if otel_active:
    with o.span("test.span", kind="server"):
        cc = o.get_context()
        ok("inside a span the context has a 32-hex trace_id",
           len(cc.get("trace_id", "")) == 32 and len(cc.get("span_id", "")) == 16)
    # propagation carrier round-trips a traceparent AND the consumer joins the same trace
    carrier = {}
    with o.span("producer.span", kind="producer"):
        producer_tid = o.get_context().get("trace_id")
        o.inject_context(carrier)
    ok("inject writes a W3C traceparent header", "traceparent" in carrier)
    consumer_tid = None
    with o.span("consumer.span", kind="consumer", carrier=carrier):
        consumer_tid = o.get_context().get("trace_id")
    # Real cross-machine link: the consumer span must land in the SAME trace as the producer
    # (32-hex trace_id carried over the W3C traceparent), not merely "a span was created".
    ok("consumer span joins the producer's trace (same trace_id across the carrier)",
       bool(producer_tid) and len(producer_tid) == 32 and producer_tid == consumer_tid)
else:
    ok("OTel active for span tests (skipped: sdk not installed)", True)
    ok("inject writes a W3C traceparent header (skipped)", True)
    ok("cross-machine link (skipped)", True)

# ---- finding A: a span NEVER swallows or replaces the caller's exception ----
# Regression for the "generator didn't stop after throw()" bug: the setup phase degrades
# (yield None) on its own failures, but once control is with the caller the ORIGINAL
# exception must propagate unchanged — not be converted into a degrade fallback or a
# RuntimeError from a double-yield.
class _Boom(Exception):
    pass


_raised = "none"
try:
    with o.span("caller.block", kind="internal", amount=1):
        raise _Boom("original-boom")
except _Boom as _e:
    _raised = ("boom", str(_e))
except Exception as _e:  # noqa: BLE001 — any other type is a failure of the property
    _raised = ("other", type(_e).__name__ + ":" + str(_e))
ok("a span re-raises the EXACT original exception from the caller's block "
   "(no swallow, no double-yield RuntimeError)",
   _raised == ("boom", "original-boom"))

# ---- structured log schema + redaction ----
captured = {}


class _Cap(logging.Handler):
    def emit(self, record):
        captured["line"] = o.JsonFormatter().format(record)


_h = _Cap()
logging.getLogger("petabyte.obs").addHandler(_h)
with o.ctx(transaction_id="tx_log_1"):
    o.event(o.EVENTS.PAYMENT_CAPTURE_COMPLETED, message="captured",
            amount=150, client_secret="pi_abc_secret_SHOULD_NOT_APPEAR",
            password="hunter2")
line = captured.get("line", "")
doc = json.loads(line) if line else {}
for key in ("timestamp", "level", "message", "service", "environment", "release", "event_name"):
    ok(f"log line has '{key}'", key in doc)
ok("log event_name is the stable name", doc.get("event_name") == "settlement.capture.completed")
ok("log carries the correlation id in the body (not a label)", doc.get("transaction_id") == "tx_log_1")
ok("secret key 'password' is redacted in logs", doc.get("password") == "«redacted»")
ok("a Stripe client_secret never appears in the log line",
   "SHOULD_NOT_APPEAR" not in line and "client_secret" in doc and doc["client_secret"] == "«redacted»")

# ---- redaction unit coverage ----
red = o.redact({"authorization": "Bearer x", "nested": {"api_key": "k", "keep": "v"},
                "msg": "card 4242424242424242 sk_live_ABCDEF"})
ok("redaction masks nested secret keys", red["nested"]["api_key"] == "«redacted»"
   and red["nested"]["keep"] == "v")
ok("redaction masks value patterns (PAN + live key)",
   "4242424242424242" not in json.dumps(red) and "sk_live_ABCDEF" not in json.dumps(red))

# ---- finding I: the 'webhook' key family must not be over-redacted ----
# webhook_event_id / webhook_id are safe correlation ids (needed for debugging + dashboards);
# only the webhook SECRET is sensitive. The key match keys on 'webhook_secret', not a bare
# 'webhook', so the ids survive while the secret is masked.
wh = o.redact({"webhook_event_id": "evt_1JZ", "webhook_id": "wh_42",
               "webhook_secret": "whsec_DEADBEEF", "stripe_webhook_secret": "whsec_XYZ"})
ok("a non-secret webhook_event_id / webhook_id is preserved (not over-redacted)",
   wh["webhook_event_id"] == "evt_1JZ" and wh["webhook_id"] == "wh_42")
ok("the webhook_secret (and stripe_webhook_secret) IS redacted",
   wh["webhook_secret"] == "«redacted»" and wh["stripe_webhook_secret"] == "«redacted»")

# ---- Prometheus bounded cardinality ----
body, ctype = o.metrics_response()
text = body.decode()
ok("metrics exposition is served", "petabyte_" in text and "text/plain" in ctype)

if o.health()["metrics"]["active"]:
    from prometheus_client.parser import text_string_to_metric_families
    # populate a few series
    o.inc_metric("petabyte_jobs_total", job_status="completed",
                 template="pytorch-matmul-v1", gpu_class="h100", environment="test")
    o.inc_metric("petabyte_transaction_transitions_total", to_state="COMPLETED",
                 payment_mode="test", environment="test")
    text = o.metrics_response()[0].decode()
    label_names = set()
    for fam in text_string_to_metric_families(text):
        for s in fam.samples:
            label_names.update(s.labels.keys())
    forbidden = {"transaction_id", "job_id", "buyer_id", "seller_id", "gpu_id",
                 "request_id", "trace_id", "payment_intent_id", "user_id"}
    ok("NO high-cardinality id is used as a metric label",
       not (label_names & forbidden))
    allowed = {"method", "route", "status_class", "environment", "reason", "outcome",
               "payment_mode", "category", "job_status", "template", "gpu_class",
               "queue", "exporter", "to_state"}
    ok("every metric label is from the controlled enumeration",
       label_names.issubset(allowed | set()))
    # route label is bounded (id segments collapsed)
    ok("route label collapses id-like segments",
       o.bounded_route("/payments/pi_abcdef123456/timeline") == "/payments/{id}/timeline")
else:
    ok("NO high-cardinality id is used as a metric label (skipped: no client)", True)
    ok("every metric label is from the controlled enumeration (skipped)", True)
    ok("route label collapses id-like segments",
       o.bounded_route("/payments/pi_abcdef123456/timeline") == "/payments/{id}/timeline")

# ---- payment spans never carry secret material ----
attrs = o._span_safe_attrs({"stripe_secret_key": "sk_live_XYZ",
                            "payment_intent_id": "pi_123", "amount": 100})
ok("span attributes drop secret-shaped keys",
   attrs.get("stripe_secret_key") == "«redacted»" and attrs.get("payment_intent_id") == "pi_123")

# ---- canonical payment modes remain distinguishable ----
# The money model has exactly three modes: test, live, sandbox (production == 'live', not
# 'real'). Invented labels (pilot/demo/real) are NOT modes and must collapse to 'other' so
# a stray value can never inflate metric cardinality or masquerade as a real mode.
modes = {o.bounded_label(m, o.PAYMENT_MODE) for m in ("test", "live", "sandbox")}
ok("canonical payment modes test/live/sandbox are all distinct bounded labels",
   modes == {"test", "live", "sandbox"})
ok("invented / unknown payment modes collapse to a bounded default ('other')",
   o.bounded_label("real", o.PAYMENT_MODE) == "other"
   and o.bounded_label("pilot", o.PAYMENT_MODE) == "other"
   and o.bounded_label("wildcardmode", o.PAYMENT_MODE) == "other")

# ---- exporter failure does not break the caller (degrade) ----
raised = False
try:
    with o.ctx(transaction_id="tx_export"):
        with o.span("settlement.capture", kind="internal", amount=100):
            o.event(o.EVENTS.PAYMENT_CAPTURE_COMPLETED, message="ok")
except Exception:
    raised = True
ok("a span + event with an unreachable exporter never raises (degrade-safe)", not raised)
ok("telemetry_export_failures metric exists for health tracking",
   "petabyte_telemetry_export_failures_total" in o.metrics_response()[0].decode()
   or not o.health()["metrics"]["active"])

# ---- GPU env never receives platform OR observability admin credentials ----
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import generate_deploy_env as G  # noqa: E402
for bad in ("GRAFANA_SERVICE_ACCOUNT_TOKEN", "LOKI_PASSWORD", "TEMPO_PASSWORD",
            "PROMETHEUS_REMOTE_WRITE_PASSWORD", "PROMETHEUS_METRICS_TOKEN",
            "OTEL_EXPORTER_OTLP_HEADERS", "STRIPE_SECRET_KEY"):
    hit = False
    try:
        G.assert_gpu_safe([("PETABYTE_API_KEY", "ok"), (bad, "x")])
    except SystemExit:
        hit = True
    ok(f"GPU env deny-list refuses {bad}", hit)

# ---- marketplace collector: scrape-time gauges with bounded labels ----
if o.health()["metrics"]["active"]:
    def _prov():
        return [
            {"name": "petabyte_sellers_online", "doc": "d",
             "labels": {"environment": "test"}, "value": 3},
            {"name": "petabyte_gpus_by_country", "doc": "d",
             "labels": {"country": "US", "environment": "test"}, "value": 5},
        ]
    ok("marketplace collector registers", o.register_marketplace_collector(_prov))
    mtext = o.metrics_response()[0].decode()
    ok("scrape-time seller gauge appears", "petabyte_sellers_online" in mtext)
    ok("gpus_by_country uses a bounded country label (not a seller id)",
       'country="US"' in mtext)
    ok("gpu_model_to_class maps to a bounded class",
       o.gpu_model_to_class("NVIDIA H100 80GB") == "h100"
       and o.gpu_model_to_class("weird") == "other")
else:
    ok("marketplace collector (skipped: no client)", True)
    ok("scrape-time seller gauge (skipped)", True)
    ok("bounded country label (skipped)", True)
    ok("gpu_model_to_class maps to a bounded class",
       o.gpu_model_to_class("NVIDIA H100 80GB") == "h100")

# ---- money-moved counters exist, are mode-separated, and never mix TEST/LIVE ----
if o.health()["metrics"]["active"]:
    for _n in ("petabyte_gmv_captured_minor_total", "petabyte_platform_fees_minor_total",
               "petabyte_seller_earnings_minor_total"):
        o.inc_metric(_n, 250, payment_mode="live", environment="test")
        o.inc_metric(_n, 99, payment_mode="test", environment="test")
    mtext = o.metrics_response()[0].decode()
    ok("GMV/fees/earnings money counters are registered (executive $ tiles)",
       all(n in mtext for n in ("petabyte_gmv_captured_minor_total",
                                "petabyte_platform_fees_minor_total",
                                "petabyte_seller_earnings_minor_total")))
    ok("money counters carry a bounded payment_mode label (TEST vs LIVE never merged)",
       'payment_mode="live"' in mtext and 'payment_mode="test"' in mtext)
    ok("money counter increments by the AMOUNT, not by 1 (live GMV == 250)",
       'petabyte_gmv_captured_minor_total{environment="test",payment_mode="live"} 250' in mtext)
else:
    ok("money counters (skipped: no client)", True)
    ok("money counters payment_mode label (skipped)", True)
    ok("money counter increments by amount (skipped)", True)

# ---- observability can be disabled only in approved environments (validator) ----
import validate_github_configuration as V  # noqa: E402
r = V.Result()
V.enforce_observability({"OBSERVABILITY_ENABLED": "false", "OTEL_ENABLED": "true"},
                        {}, "production", r)
ok("production rejects OBSERVABILITY_ENABLED=false", not r.ok)
r2 = V.Result()
V.enforce_observability({"OBSERVABILITY_ENABLED": "true", "OTEL_ENABLED": "true",
                         "OTEL_EXPORTER_OTLP_ENDPOINT": "http://obs:4317",
                         "OBSERVABILITY_REQUIRED": "false"}, {}, "staging", r2)
ok("staging with telemetry configured passes", r2.ok)

print(f"\n=== observability: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
