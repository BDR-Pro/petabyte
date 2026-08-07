# Observability audit

First-phase audit of Petabyte's telemetry, and the plan that this change set implements.
Every row was verified against the code (not assumed). Status legend: **✅ done** in this
change set · **🟡 partial** (foundation shipped, deeper per-step spans to follow) ·
**⛔ blocked-external** (needs the observability server, which the CI sandbox cannot reach).

> Verification boundary: this sandbox cannot reach the observability server
> (`IP_LOGS_SERVER` is a placeholder and outbound is restricted). Anything that requires a
> trace/log/metric to *land* on that server is verified from the deploy runner or the
> DigitalOcean boxes via `scripts/observability_smoke_test.py`, never faked here.

## What already existed (before this change)

| Area | Found |
|---|---|
| Logging | stdlib `logging.getLogger(...)` in many modules; **plain text**, no JSON, no central config, no redaction. |
| Metrics | `/metrics` = an **HTML investor page**; `/metrics/overview` = business JSON. **No Prometheus exposition** anywhere. |
| Tracing | none (no OpenTelemetry). |
| Sentry | `sentry-sdk` dependency + a minimal `sentry_sdk.init(dsn, traces_sample_rate=0.1)` gated on `SENTRY_DSN`; no release/env correlation, no scrubbing. |
| Redis | **not used** — rate limiting is in-process; a code comment says "move to Redis when we run more than one". |
| Request id | `X-Request-ID` minted in middleware (`secrets.token_hex(8)`), echoed in the response + audit log. No validation of an incoming id; no trace correlation. |
| Transaction id | `ComputeTransaction.public_id` + an append-only `ComputeTxEvent` history; single transition chokepoint `stripe_connect.transition()`. |
| Job id | `Task.id` returned by `/jobs/next`; no trace context in the envelope. |
| Stripe ids | `payment_intent_id` / `charge_id` / `transfer_id` on the tx; `PaymentOperation` + `StripeWebhookEvent` tables. |
| Health | `/healthz`, `/readyz`, `/health/live`, `/health/ready` (with maintenance-stale). |
| Background work | `tools/reaper.py`, `tools/payout_worker.py`, `tools/idle_reconcile.py` (loop services). |
| DB / HTTP clients | SQLAlchemy; `httpx` for Stripe/Mailgun/agent (31 call sites). |
| Subprocess/Docker | seller agent runs workloads via `docker run` (`lumaris_agent/notebook.py`), GPU detect via `nvidia-smi`. |
| Dashboards / alerts | none in the repo. |
| Env vars | `LOG_LEVEL`, `SENTRY_DSN` only. |

## Component-by-component

Each: current → missing → impact → implementation → security → verification → status.

### Backend API (`petabyte-api`)
- **Current:** request-id middleware, security headers, in-process rate limit.
- **Missing:** JSON logs, request metrics, traces, auth/authz/ratelimit/validation signals.
- **Impact:** no latency/error SLOs; can't reconstruct a request.
- **Implementation:** `observability.py` core + middleware span (W3C-parented) + bounded
  request metrics (`petabyte_http_requests_total`, `_request_duration_seconds`,
  `_in_flight_requests`) + `EVENTS.HTTP_REQUEST`/`RATELIMIT_BLOCKED`/`UNHANDLED_EXCEPTION`;
  `X-Trace-Id` response header. Protected Prometheus endpoint at `/internal/metrics`.
- **Security:** no bodies logged; secret redaction; metrics endpoint token/loopback-gated.
- **Verify:** `observability_test.py`; `curl -H "Authorization: Bearer $TOKEN" .../internal/metrics`.
- **Status:** ✅ done.

### Correlation model
- **Missing:** one context spanning services; W3C propagation; validated incoming ids.
- **Implementation:** `observability.py` contextvars (`request_id`, `trace_id`, `span_id`,
  `run_id`, `transaction_id`, `booking_id`, `reservation_id`, `job_id`, `buyer_id`,
  `seller_id`, `gpu_id`, `agent_id`, `template_*`, Stripe ids, `webhook_event_id`,
  `data_class`), `sanitize_incoming_request_id`, W3C `inject`/`extract`.
- **Verify:** propagation test (API span → worker span share `trace_id`), smoke test.
- **Status:** ✅ done.

### Database
- **Missing:** query/txn duration, pool wait, rollback/deadlock metrics.
- **Implementation:** `postgres_exporter` (documented in `observability/prometheus/`); app
  spans wrap the settlement path. Deeper per-query spans: follow-up.
- **Security:** never capture raw SQL with user values.
- **Status:** 🟡 partial (exporter + settlement spans; SQLAlchemy auto-instrumentation is a
  documented next step).

### Redis
- **Current:** none.
- **Implementation:** `redis_client.py` — namespaced keys, TTLs, atomic ops, safe
  compare-and-del locks, connect/op timeouts, **circuit breaker**, spans + failure metric;
  wired to the credential rate-limiter (shared across workers) with in-process fallback.
- **Security:** never the ledger; values never in telemetry; TTLs + bounded keys.
- **Verify:** `redis_client.health()`, smoke test Redis tier.
- **Status:** ✅ done (optional; degrades to in-process when unset).

### Background workers
- **Implementation:** JSON logging applies process-wide; queue metrics
  (`petabyte_queue_depth`) + worker dashboard. Per-worker spans: follow-up.
- **Status:** 🟡 partial.

### Stripe operations
- **Implementation:** the `transition()` spine emits per-state events + the transitions
  counter; `capture()`/`transfer_to_seller()` emit capture/commission/seller-earning/
  transfer events **with amounts** (minor units, no secrets) + outcome metrics; webhook
  metrics defined (`petabyte_webhooks_total`, invalid-signature, duplicate).
- **Security:** never logs keys/client secrets/webhook secrets/card data (redaction +
  span-attr scrub, tested).
- **Status:** ✅ done for capture/transfer/commission; 🟡 per-webhook span wiring is next.

### GPU reservation & scheduling
- **Implementation:** `job.dispatch` PRODUCER span injects trace context into the job
  envelope; `EVENTS.JOB_DISPATCHED`, `GPU_RESERVATION_*` via the spine;
  `petabyte_reservation_conflicts_total`, `petabyte_routing_duration_seconds`.
- **Security:** candidate GPU ids not attached en masse.
- **Status:** 🟡 partial (dispatch + reservation events done; routing-score spans next).

### Seller agent (`petabyte-seller-agent`)
- **Implementation:** `agent_telemetry.py` — JSON logs + redaction, optional OTLP,
  **W3C extraction from the job envelope** (execution joins the platform trace), events for
  startup/heartbeat/heartbeat-missed/job-received/execution start·complete·fail. Degrade-safe:
  the agent keeps running if the collector is down.
- **Status:** ✅ done for the loop; container/CUDA sub-steps: follow-up.

### GPU workload execution & result validation
- **Implementation:** execution span on the agent; validation events/metrics defined
  (`result.validation.passed/failed`, `petabyte_jobs_total{job_status=validated|invalid}`).
- **Status:** 🟡 partial (spine + agent execution span; per-validation-step spans next).

### Settlement
- **Implementation:** metering/capture/commission/seller-earning/transfer events + metrics
  (see Stripe). Ledger-imbalance + reconciliation metrics defined for alerting.
- **Status:** ✅ done for the money spine.

### Frontend / browser
- **Status:** ⛔ documented approach (browser OTel + Sentry) in
  `docs/OBSERVABILITY_ARCHITECTURE.md`; the app is server-rendered, so this is a
  deliberate next phase, not wired in this change set. Honestly marked pending.

### Sentry
- **Implementation:** env + release + `service` tag, PII off, `before_send` scrubs via the
  same redaction policy, sample rates from config.
- **Status:** ✅ done (backend); worker/agent Sentry: follow-up.

## Standardisation (no competing systems)
We standardised the **existing** `logging` (JSON formatter on the root handler) and the
**existing** `sentry-sdk` rather than adding a second stack. OpenTelemetry is the new,
single tracing/metrics standard. Nothing duplicates another tool.

## Verification summary
- Offline (this sandbox): `observability_test.py` (correlation, redaction, bounded
  cardinality, degrade-safety, access control, TEST/DEMO/PILOT/REAL), `config_test.py`,
  `check_configuration_drift.py`, `observability_smoke_test.py` (local tier + OTel
  propagation proof with a bogus collector).
- On the deploy runner / DO boxes (⛔ here): the smoke test's remote tier confirms the
  trace reaches Tempo, logs reach Loki, Grafana datasources are healthy, and a controlled
  Sentry event lands. See `docs/TRANSACTION_TRACE_GUIDE.md` and
  `docs/INVESTOR_OBSERVABILITY_DEMO.md`.
