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
    # propagation carrier round-trips a traceparent
    carrier = {}
    with o.span("producer.span", kind="producer"):
        o.inject_context(carrier)
    ok("inject writes a W3C traceparent header", "traceparent" in carrier)
    with o.span("consumer.span", kind="consumer", carrier=carrier):
        pass
    ok("a span can be created from an incoming carrier (cross-machine link)", True)
else:
    ok("OTel active for span tests (skipped: sdk not installed)", True)
    ok("inject writes a W3C traceparent header (skipped)", True)
    ok("cross-machine link (skipped)", True)

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

# ---- TEST / DEMO / PILOT / REAL remain distinguishable ----
modes = {o.bounded_label(m, o.PAYMENT_MODE) for m in ("test", "live", "pilot", "demo", "real")}
ok("payment modes test/live/pilot/demo/real are all distinct bounded labels",
   modes == {"test", "live", "pilot", "demo", "real"})
ok("an unknown payment mode collapses to a bounded default",
   o.bounded_label("wildcardmode", o.PAYMENT_MODE) == "other")

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
