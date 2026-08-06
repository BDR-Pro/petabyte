"""Petabyte observability core — correlation, structured logging + redaction, optional
OpenTelemetry tracing, and bounded-cardinality Prometheus metrics.

Design rules (all non-negotiable):
  * Import-safe and degrade-safe. If opentelemetry / prometheus_client are not installed,
    or OBSERVABILITY is disabled, everything here becomes a cheap no-op. Telemetry MUST
    NEVER break payment settlement or job execution (OBSERVABILITY_FAILURE_MODE=degrade).
  * One correlation model everywhere (contextvars): request_id + W3C trace_id/span_id plus
    business IDs (transaction_id, job_id, reservation_id, buyer/seller/gpu/agent, Stripe
    object ids, template). Business IDs live in LOG/TRACE bodies — NEVER as metric labels.
  * Structured JSON logs with centralized redaction (never log secrets / card data /
    tokens / cookies / full workload inputs).
  * Prometheus labels are drawn from small controlled enumerations only (bounded
    cardinality). No user/transaction/job/GPU id is ever a label value.

Public API:
    from observability import (
        obs, ctx, bind_context, get_context, new_request_id, redact,
        configure_logging, init_observability, span, event, metrics_response,
        EVENTS, SERVICE, bounded_label, health,
    )
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

# --------------------------------------------------------------------------- config
def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _first(*names: str, default: str = "") -> str:
    """First non-empty env var among `names` (build/runtime identity metadata with a
    fallback chain — resolved indirectly on purpose, these are not deploy-config knobs)."""
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return default


OBS_ENABLED = _b("OBSERVABILITY_ENABLED", True)
OTEL_ENABLED = OBS_ENABLED and _b("OTEL_ENABLED", True)
METRICS_ENABLED = OBS_ENABLED and _b("PROMETHEUS_ENABLED", True) and _b("OTEL_METRICS_ENABLED", True)
LOG_FORMAT = os.getenv("LOG_FORMAT", "json").strip().lower()
LOG_REDACTION_ENABLED = _b("LOG_REDACTION_ENABLED", True)
FAILURE_MODE = os.getenv("OBSERVABILITY_FAILURE_MODE", "degrade").strip().lower()

OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
OTLP_PROTOCOL = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").strip().lower()
TRACE_SAMPLE_RATIO = _f("OTEL_TRACE_SAMPLE_RATIO", 1.0)
EXPORT_TIMEOUT_S = _i("OBSERVABILITY_EXPORT_TIMEOUT_SECONDS", 5)
QUEUE_SIZE = _i("OBSERVABILITY_QUEUE_SIZE", 2048)
BATCH_SIZE = _i("OBSERVABILITY_BATCH_SIZE", 512)

SERVICE_NAMESPACE = os.getenv("OTEL_SERVICE_NAMESPACE", "petabyte")
ENVIRONMENT = _first("DEPLOYMENT_ENVIRONMENT", "ENVIRONMENT", "APP_ENV",
                     default="development")
RELEASE = _first("RELEASE_VERSION", "PETABYTE_RELEASE_SHA", "GITHUB_SHA", default="dev")
HOST_ROLE = _first("PETABYTE_HOST_ROLE")


class _Service:
    """Canonical service names (also OTLP service.name)."""
    WEB = "petabyte-web"
    API = "petabyte-api"
    WORKER = "petabyte-worker"
    SCHEDULER = "petabyte-scheduler"
    STRIPE_WEBHOOK = "petabyte-stripe-webhook"
    SELLER_AGENT = "petabyte-seller-agent"
    GPU_EXECUTOR = "petabyte-gpu-executor"
    RESULT_VALIDATOR = "petabyte-result-validator"
    SETTLEMENT = "petabyte-settlement"


SERVICE = _Service()
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", SERVICE.API).strip()


class EVENTS:
    """Stable event names (log `event_name` + span event). Never rename in place — these
    are consumed by dashboards, alerts, runbooks, and future AI ops features."""
    # request / auth
    HTTP_REQUEST = "http.request.completed"
    AUTH_FAILED = "auth.failed"
    AUTHZ_DENIED = "authz.denied"
    RATELIMIT_BLOCKED = "ratelimit.blocked"
    VALIDATION_FAILED = "request.validation.failed"
    UNHANDLED_EXCEPTION = "unhandled.exception"
    # payment / settlement
    QUOTE_CALCULATED = "quote.calculated"
    PAYMENT_AUTH_REQUESTED = "payment.authorization.requested"
    PAYMENT_AUTH_CONFIRMED = "payment.authorization.confirmed"
    PAYMENT_CAPTURE_COMPLETED = "settlement.capture.completed"
    PAYMENT_CAPTURE_FAILED = "settlement.capture.failed"
    COMMISSION_RECORDED = "settlement.commission.recorded"
    SELLER_EARNING_CREATED = "settlement.seller_earning.created"
    SELLER_TRANSFER_CREATED = "seller.transfer.created"
    SELLER_TRANSFER_FAILED = "seller.transfer.failed"
    METERING_FINALIZED = "settlement.metering.finalized"
    REFUND_CREATED = "settlement.refund.created"
    # gpu / job lifecycle
    GPU_RESERVATION_CREATED = "gpu.reservation.created"
    GPU_RESERVATION_CONFLICT = "gpu.reservation.conflict"
    JOB_DISPATCHED = "job.dispatched"
    JOB_EXECUTION_STARTED = "job.execution.started"
    JOB_EXECUTION_COMPLETED = "job.execution.completed"
    JOB_EXECUTION_FAILED = "job.execution.failed"
    RESULT_UPLOADED = "result.uploaded"
    RESULT_VALIDATION_PASSED = "result.validation.passed"
    RESULT_VALIDATION_FAILED = "result.validation.failed"
    # transaction spine
    TX_TRANSITION = "transaction.transition"
    TX_COMPLETED = "transaction.completed"
    # webhooks
    WEBHOOK_RECEIVED = "webhook.received"
    WEBHOOK_VERIFIED = "webhook.verified"
    WEBHOOK_PROCESSING_FAILED = "webhook.processing.failed"
    WEBHOOK_DUPLICATE = "webhook.duplicate"
    # agent
    AGENT_HEARTBEAT_MISSED = "agent.heartbeat.missed"
    AGENT_ENROLLED = "agent.enrolled"
    AGENT_RECONNECTED = "agent.reconnected"
    # redis / infra
    REDIS_UNAVAILABLE = "redis.unavailable"
    LOCK_ACQUIRED = "redis.lock.acquired"
    LOCK_CONFLICT = "redis.lock.conflict"


# Controlled label enumerations (bounded cardinality). Values outside these collapse to
# "other" via bounded_label(), so a metric can never explode into unbounded series.
JOB_STATUS = {"queued", "running", "completed", "failed", "validated", "invalid", "cancelled"}
PAYMENT_MODE = {"test", "live", "sandbox", "pilot", "demo", "real"}
GPU_CLASS = {"h100", "a100", "l40s", "l4", "a10", "rtx4090", "rtx3090", "t4", "v100", "other"}
FAILURE_CATEGORY = {"none", "timeout", "validation", "gpu_offline", "payment", "network",
                    "internal", "conflict", "rate_limited", "auth"}
OUTCOME = {"success", "failure", "skipped", "retry"}


def bounded_label(value, allowed: set, default: str = "other") -> str:
    """Clamp a would-be metric label to a controlled enumeration (bounded cardinality)."""
    v = ("" if value is None else str(value)).strip().lower()
    return v if v in allowed else default


_ID_SEG = re.compile(
    r"^([0-9]+"                       # pure numeric id
    r"|[0-9a-fA-F-]{16,}"             # long hex / uuid
    r"|[A-Za-z0-9_-]{20,}"            # long opaque token
    r"|[A-Za-z]{1,6}_[A-Za-z0-9]{4,}"  # Stripe-style prefix_id (pi_/cs_/ch_/tx_…)
    r")$")


def bounded_route(path: str) -> str:
    """Collapse id-like path segments to `{id}` so a route makes a BOUNDED metric label.
    `/payments/pi_abc123/timeline` -> `/payments/{id}/timeline`. Prefer the framework's
    matched route template when available; this is the safe fallback."""
    if not path:
        return "/"
    parts = []
    for seg in path.split("/"):
        parts.append("{id}" if seg and _ID_SEG.match(seg) else seg)
    out = "/".join(parts) or "/"
    return out[:120]


# --------------------------------------------------------------------------- context
_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("petabyte_obs_ctx", default={})

# The full correlation vocabulary. Only these keys are recognised in the context.
CONTEXT_KEYS = (
    "request_id", "trace_id", "span_id", "run_id", "transaction_id", "booking_id",
    "reservation_id", "job_id", "buyer_id", "seller_id", "gpu_id", "agent_id",
    "template_name", "template_version", "payment_intent_id", "charge_id", "transfer_id",
    "refund_id", "webhook_event_id", "data_class",
)

_REQ_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")


def new_request_id() -> str:
    import secrets
    return secrets.token_hex(8)


def sanitize_incoming_request_id(value: str | None) -> str | None:
    """Accept a caller-supplied request id ONLY after format + length validation."""
    if not value:
        return None
    value = value.strip()
    return value if _REQ_ID_RE.match(value) else None


def bind_context(**kw) -> None:
    """Merge correlation fields into the current context (ignores None + unknown keys)."""
    cur = dict(_CTX.get())
    for k, v in kw.items():
        if k in CONTEXT_KEYS and v is not None:
            cur[k] = str(v)
    _CTX.set(cur)


def get_context() -> dict:
    return dict(_CTX.get())


def clear_context() -> None:
    _CTX.set({})


@contextlib.contextmanager
def ctx(**kw):
    """Scope correlation fields to a block, restoring the prior context on exit."""
    token = _CTX.set({**_CTX.get(), **{k: str(v) for k, v in kw.items()
                                       if k in CONTEXT_KEYS and v is not None}})
    try:
        yield
    finally:
        _CTX.reset(token)


# --------------------------------------------------------------------------- redaction
# Keys whose values are always dropped, and substring patterns that mark a key sensitive.
_REDACT_KEYS = {
    "password", "passwd", "secret", "token", "authorization", "cookie", "session",
    "api_key", "apikey", "private_key", "client_secret", "webhook_secret", "database_url",
    "redis_url", "card", "cvc", "cvv", "account_number", "routing_number", "ssn",
    "access_token", "refresh_token", "id_token", "set-cookie", "x-api-key",
    "stripe_secret_key", "server_private_key", "secret_key", "dsn",
}
_REDACT_SUBSTR = ("secret", "password", "passwd", "token", "api_key", "apikey",
                  "private_key", "client_secret", "webhook", "cookie", "authorization",
                  "credential", "cvc", "cvv", "card_number", "account_number",
                  "routing_number")
# Value patterns that must be masked wherever they appear, even in a free-text message.
_VALUE_PATTERNS = [
    re.compile(r"sk_(live|test)_[A-Za-z0-9]+"),        # Stripe secret key
    re.compile(r"rk_(live|test)_[A-Za-z0-9]+"),        # Stripe restricted key
    re.compile(r"whsec_[A-Za-z0-9]+"),                 # Stripe webhook secret
    re.compile(r"(pi|seti|cs|ch)_[A-Za-z0-9]+_secret_[A-Za-z0-9]+"),  # client secrets
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),          # bearer tokens
    re.compile(r"\b\d{13,19}\b"),                       # PAN-like long digit runs
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),  # emails (PII)
]
_REDACTED = "«redacted»"


def _key_is_sensitive(key: str) -> bool:
    k = key.lower()
    if k in _REDACT_KEYS:
        return True
    return any(s in k for s in _REDACT_SUBSTR)


def _mask_value(s: str) -> str:
    for pat in _VALUE_PATTERNS:
        s = pat.sub(_REDACTED, s)
    return s


def redact(obj, _depth: int = 0):
    """Recursively redact secrets by key name and by value pattern. Bounded depth so a
    pathological structure can never hang logging."""
    if not LOG_REDACTION_ENABLED or _depth > 6:
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _key_is_sensitive(k):
                out[k] = _REDACTED
            else:
                out[k] = redact(v, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth + 1) for v in obj][:200]
    if isinstance(obj, str):
        return _mask_value(obj)
    return obj


# --------------------------------------------------------------------------- logging
class JsonFormatter(logging.Formatter):
    """Structured JSON log lines with correlation context + redaction. One line per event."""

    _STD = frozenset((
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
        "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
        "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    ))

    def format(self, record: logging.LogRecord) -> str:
        base = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
                         .isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "message": _mask_value(record.getMessage()) if LOG_REDACTION_ENABLED
                       else record.getMessage(),
            "service": SERVICE_NAME,
            "environment": ENVIRONMENT,
            "release": RELEASE,
            "logger": record.name,
        }
        # correlation context (only non-empty)
        for k, v in get_context().items():
            base.setdefault(k, v)
        # explicit event_name + structured extra fields
        extra = {k: v for k, v in record.__dict__.items()
                 if k not in self._STD and not k.startswith("_") and k not in base}
        if extra:
            base.update(redact(extra))
        base.setdefault("event_name", extra.get("event_name") if extra else None)
        if record.exc_info:
            base["exception"] = _mask_value(self.formatException(record.exc_info))
        return json.dumps(base, default=str, ensure_ascii=False)


_configured = False


def configure_logging() -> None:
    """Install the JSON formatter on the root handler once. Safe to call repeatedly."""
    global _configured
    if _configured:
        return
    _configured = True
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    if LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
    # replace existing handlers so we don't double-log
    root.handlers = [handler]


_logger = logging.getLogger("petabyte.obs")


def event(name: str, *, level: int = logging.INFO, **fields) -> None:
    """Emit a structured event: a JSON log line with a stable event_name AND a span event
    on the current OTel span (if any). Business identifiers belong here, not in metrics."""
    try:
        _logger.log(level, fields.pop("message", name), extra={"event_name": name, **fields})
        sp = _current_span()
        if sp is not None:
            with contextlib.suppress(Exception):
                sp.add_event(name, attributes=_span_safe_attrs(fields))
    except Exception:  # noqa: BLE001 — telemetry must never raise into the caller
        if FAILURE_MODE != "degrade":
            raise


# --------------------------------------------------------------------------- tracing
_TRACER = None
_otel_ok = False


def _span_safe_attrs(fields: dict) -> dict:
    out = {}
    for k, v in redact(fields).items():
        if isinstance(v, (str, bool, int, float)):
            out[k] = v
        elif v is not None:
            out[k] = str(v)
    return out


def init_tracing() -> bool:
    """Set up OTLP tracing. Returns True if a real exporter was installed. Never raises."""
    global _TRACER, _otel_ok
    if not OTEL_ENABLED or not OTLP_ENDPOINT:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ParentBased, TraceIdRatioBased, ALWAYS_ON)
        if OTLP_PROTOCOL.startswith("http"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        attrs = {
            "service.name": SERVICE_NAME,
            "service.namespace": SERVICE_NAMESPACE,
            "service.version": RELEASE,
            "deployment.environment": ENVIRONMENT,
        }
        if HOST_ROLE:
            attrs["petabyte.host_role"] = HOST_ROLE
        if RELEASE:
            attrs["petabyte.release_sha"] = RELEASE
        sampler = (ALWAYS_ON if TRACE_SAMPLE_RATIO >= 1.0
                   else ParentBased(TraceIdRatioBased(TRACE_SAMPLE_RATIO)))
        provider = TracerProvider(resource=Resource.create(attrs), sampler=sampler)
        exporter = OTLPSpanExporter(
            endpoint=OTLP_ENDPOINT,
            timeout=EXPORT_TIMEOUT_S,
        )
        provider.add_span_processor(BatchSpanProcessor(
            exporter, max_queue_size=QUEUE_SIZE, max_export_batch_size=BATCH_SIZE,
            schedule_delay_millis=2000, export_timeout_millis=EXPORT_TIMEOUT_S * 1000))
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer("petabyte")
        _otel_ok = True
        return True
    except Exception as e:  # noqa: BLE001
        _logger.warning("OTel tracing init skipped", extra={"event_name": "otel.init.skipped",
                                                            "reason": str(e)})
        return False


def _current_span():
    if not _otel_ok:
        return None
    try:
        from opentelemetry import trace
        sp = trace.get_current_span()
        return sp if sp and sp.get_span_context().is_valid else None
    except Exception:  # noqa: BLE001
        return None


def inject_context(carrier: dict) -> dict:
    """Inject the current W3C trace context into a carrier dict (for outbound propagation
    across Redis jobs, HTTP calls, and the seller agent). No-op if OTel is inactive."""
    if not _otel_ok:
        return carrier
    with contextlib.suppress(Exception):
        from opentelemetry.propagate import inject
        inject(carrier)
    return carrier


@contextlib.contextmanager
def span(name: str, *, kind: str = "internal", carrier: dict | None = None, **attrs):
    """Start a span (no-op if OTel isn't active). If `carrier` (incoming headers / job
    envelope) is given, its W3C trace context becomes the parent so the trace spans
    machines. Records the exception + status on error but NEVER swallows it — the caller's
    control flow is unchanged. Refreshes the context's trace_id/span_id so structured logs
    inside the block correlate."""
    if not _otel_ok or _TRACER is None:
        yield None
        return
    try:
        from opentelemetry import trace
        from opentelemetry.trace import SpanKind
        parent = None
        if carrier:
            with contextlib.suppress(Exception):
                from opentelemetry.propagate import extract
                parent = extract(carrier)
        kmap = {"server": SpanKind.SERVER, "client": SpanKind.CLIENT,
                "producer": SpanKind.PRODUCER, "consumer": SpanKind.CONSUMER}
        with _TRACER.start_as_current_span(
                name, kind=kmap.get(kind, SpanKind.INTERNAL), context=parent) as sp:
            for k, v in _span_safe_attrs(attrs).items():
                sp.set_attribute(k, v)
            sctx = sp.get_span_context()
            token = _CTX.set({**_CTX.get(),
                              "trace_id": format(sctx.trace_id, "032x"),
                              "span_id": format(sctx.span_id, "016x")})
            try:
                yield sp
            except Exception as exc:
                with contextlib.suppress(Exception):
                    sp.record_exception(exc)
                    sp.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                raise
            finally:
                _CTX.reset(token)
    except Exception:  # noqa: BLE001 — a broken tracer must not break the caller
        if FAILURE_MODE != "degrade":
            raise
        yield None


# --------------------------------------------------------------------------- metrics
_metrics = {}
_prom_ok = False
_REGISTRY = None


class _NoMetric:
    def labels(self, *a, **k):
        return self

    def inc(self, *a, **k):
        pass

    def observe(self, *a, **k):
        pass

    def set(self, *a, **k):
        pass


def init_metrics() -> bool:
    """Define the Prometheus metric set (bounded labels only). No-op if the client is
    absent. Returns True if real metrics are active."""
    global _prom_ok, _REGISTRY
    if not METRICS_ENABLED:
        return False
    try:
        from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
        _REGISTRY = CollectorRegistry(auto_describe=True)

        def C(name, doc, labels=()):
            _metrics[name] = Counter(name, doc, labels, registry=_REGISTRY)

        def G(name, doc, labels=()):
            _metrics[name] = Gauge(name, doc, labels, registry=_REGISTRY)

        def H(name, doc, labels=(), buckets=None):
            kw = {"registry": _REGISTRY}
            if buckets:
                kw["buckets"] = buckets
            _metrics[name] = Histogram(name, doc, labels, **kw)

        # API
        C("petabyte_http_requests_total", "HTTP requests",
          ("method", "route", "status_class", "environment"))
        H("petabyte_http_request_duration_seconds", "HTTP request duration",
          ("method", "route", "environment"))
        G("petabyte_http_in_flight_requests", "In-flight HTTP requests", ("environment",))
        C("petabyte_auth_failures_total", "Authentication failures", ("reason", "environment"))
        C("petabyte_authz_denials_total", "Authorization denials", ("environment",))
        C("petabyte_ratelimit_blocks_total", "Rate-limit blocks", ("route", "environment"))
        C("petabyte_validation_failures_total", "Request validation failures", ("environment",))
        # payments / settlement
        C("petabyte_payment_intent_attempts_total", "PaymentIntent creation attempts",
          ("outcome", "payment_mode", "environment"))
        C("petabyte_payment_authorizations_total", "Payment authorizations",
          ("outcome", "payment_mode", "environment"))
        C("petabyte_payment_captures_total", "Payment captures",
          ("outcome", "payment_mode", "environment"))
        H("petabyte_payment_capture_duration_seconds", "Capture latency",
          ("payment_mode", "environment"))
        C("petabyte_seller_transfers_total", "Seller transfers",
          ("outcome", "payment_mode", "environment"))
        C("petabyte_refunds_total", "Refunds", ("payment_mode", "environment"))
        C("petabyte_webhooks_total", "Stripe webhooks",
          ("category", "outcome", "environment"))
        C("petabyte_webhook_invalid_signature_total", "Invalid webhook signatures",
          ("environment",))
        C("petabyte_webhook_duplicate_total", "Duplicate webhook events", ("environment",))
        C("petabyte_reconciliation_discrepancies_total", "Reconciliation discrepancies",
          ("environment",))
        C("petabyte_ledger_imbalance_total", "Ledger imbalance detections", ("environment",))
        # jobs / marketplace
        C("petabyte_jobs_total", "Jobs by terminal status",
          ("job_status", "template", "gpu_class", "environment"))
        H("petabyte_job_startup_seconds", "Job startup latency", ("gpu_class", "environment"))
        H("petabyte_job_duration_seconds", "Job execution duration", ("gpu_class", "environment"))
        C("petabyte_reservation_conflicts_total", "Reservation conflicts", ("environment",))
        H("petabyte_routing_duration_seconds", "GPU routing duration", ("environment",))
        G("petabyte_gpus_online", "Online GPUs", ("environment",))
        G("petabyte_gpus_available", "Available GPUs", ("environment",))
        G("petabyte_gpus_reserved", "Reserved GPUs", ("environment",))
        G("petabyte_jobs_running", "Running jobs", ("environment",))
        G("petabyte_queue_depth", "Queue depth", ("queue", "environment"))
        # transaction spine
        C("petabyte_transaction_transitions_total", "Transaction state transitions",
          ("to_state", "payment_mode", "environment"))
        # agents
        G("petabyte_agents_online", "Connected seller agents", ("environment",))
        # telemetry health
        C("petabyte_telemetry_export_failures_total", "Telemetry export failures",
          ("exporter", "environment"))
        _prom_ok = True
        return True
    except Exception as e:  # noqa: BLE001
        _logger.warning("Prometheus metrics init skipped",
                        extra={"event_name": "metrics.init.skipped", "reason": str(e)})
        return False


def metric(name: str):
    """Return a metric handle, or a no-op if metrics are disabled/unavailable."""
    return _metrics.get(name, _NoMetric())


def observe_metric(name: str, value: float, **labels) -> None:
    try:
        m = _metrics.get(name)
        if m is None:
            return
        (m.labels(**labels) if labels else m).observe(value)
    except Exception:  # noqa: BLE001
        pass


def inc_metric(name: str, value: float = 1, **labels) -> None:
    try:
        m = _metrics.get(name)
        if m is None:
            return
        (m.labels(**labels) if labels else m).inc(value)
    except Exception:  # noqa: BLE001
        pass


def set_metric(name: str, value: float, **labels) -> None:
    try:
        m = _metrics.get(name)
        if m is None:
            return
        (m.labels(**labels) if labels else m).set(value)
    except Exception:  # noqa: BLE001
        pass


def metrics_response():
    """Return (body: bytes, content_type: str) for the Prometheus scrape endpoint."""
    if not _prom_ok or _REGISTRY is None:
        return b"# observability metrics disabled\n", "text/plain; charset=utf-8"
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    return generate_latest(_REGISTRY), CONTENT_TYPE_LATEST


# --------------------------------------------------------------------------- lifecycle
_started = False


def init_observability(service_name: str | None = None) -> dict:
    """Initialise logging + tracing + metrics for a service. Idempotent, never raises."""
    global _started, SERVICE_NAME
    if service_name:
        SERVICE_NAME = service_name
    if _started:
        return health()
    _started = True
    try:
        configure_logging()
        init_metrics()
        init_tracing()
        _logger.info("observability initialised",
                     extra={"event_name": "observability.initialised",
                            "otel": _otel_ok, "metrics": _prom_ok,
                            "endpoint_configured": bool(OTLP_ENDPOINT)})
    except Exception as e:  # noqa: BLE001
        if FAILURE_MODE != "degrade":
            raise
        logging.getLogger("petabyte.obs").warning(f"observability init degraded: {e}")
    return health()


def health() -> dict:
    """Health of the observability integrations (for /health/observability)."""
    return {
        "enabled": OBS_ENABLED,
        "failure_mode": FAILURE_MODE,
        "logging_json": LOG_FORMAT == "json",
        "redaction": LOG_REDACTION_ENABLED,
        "tracing": {"enabled": OTEL_ENABLED, "active": _otel_ok,
                    "endpoint_configured": bool(OTLP_ENDPOINT),
                    "protocol": OTLP_PROTOCOL, "sample_ratio": TRACE_SAMPLE_RATIO},
        "metrics": {"enabled": METRICS_ENABLED, "active": _prom_ok},
        "service": SERVICE_NAME, "environment": ENVIRONMENT, "release": RELEASE,
    }


class _Obs:
    """Convenience facade so callers can `from observability import obs`."""
    EVENTS = EVENTS
    SERVICE = SERVICE
    span = staticmethod(span)
    event = staticmethod(event)
    ctx = staticmethod(ctx)
    bind = staticmethod(bind_context)
    inc = staticmethod(inc_metric)
    observe = staticmethod(observe_metric)
    set = staticmethod(set_metric)
    bounded = staticmethod(bounded_label)
    bounded_route = staticmethod(bounded_route)
    inject = staticmethod(inject_context)
    redact = staticmethod(redact)
    health = staticmethod(health)


obs = _Obs()
