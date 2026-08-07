# Runbook: Observability Pipeline Failure

The telemetry pipeline itself is failing: OTLP export to the Collector, Prometheus
scrape, Loki ingestion, Tempo, or Sentry. Petabyte is designed so this **degrades and
never breaks** the app (`OBSERVABILITY_FAILURE_MODE=degrade`), but you are now flying
partially blind and must restore visibility.

## Symptoms

- `petabyte_telemetry_export_failures_total{exporter="..."}` incrementing.
- `/health/observability` shows `tracing.active=false` or `metrics.active=false` while
  the app is otherwise healthy.
- Gaps in Grafana: missing traces in Tempo, missing metrics series, missing log lines
  in Loki, or Sentry not receiving errors.
- Log line `event_name="otel.init.skipped"` or `metrics.init.skipped` at startup.

## Impact

- **No user-facing or financial impact by design** — settlement and job execution are
  unaffected. The impact is operational: reduced ability to detect and debug other
  incidents. Restore quickly so you're not blind during a real event.

## Dashboard

**Infrastructure** (Collector / Prometheus / Loki / Tempo health) and the
`/health/observability` endpoint on each service.

## Loki query

If Loki is up but exports are failing elsewhere:

```logql
{environment="production"} | json | event_name=~"otel.init.skipped|metrics.init.skipped"
```

If Loki ingestion itself is the failure, this query returns nothing — fall back to
reading container stdout on the box and the Collector's own logs.

## Metrics to inspect

- Export failures by exporter (otlp/prometheus/loki/tempo/sentry):
  ```promql
  sum by (exporter) (increase(petabyte_telemetry_export_failures_total{environment="production"}[15m]))
  ```
- Scrape target liveness (if a target is down, its series go stale):
  ```promql
  up{job=~"petabyte-.*"}
  ```
- Collector/Prometheus/Loki/Tempo own health metrics on the Infrastructure dashboard
  (queue lengths, dropped spans, ingestion errors).

## Trace to inspect

- If Tempo is the failing component you can't use it — diagnose from
  `petabyte_telemetry_export_failures_total{exporter="tempo"}`, the Collector logs, and
  `/health/observability` (`tracing.active`, `endpoint_configured`, `protocol`).
- If only some services are missing from Tempo, check their `OTEL_EXPORTER_OTLP_ENDPOINT`
  / `OTEL_EXPORTER_OTLP_PROTOCOL` and network path to the Collector.

## Safe first actions

1. Confirm blast radius on `/health/observability` for each service: is it tracing,
   metrics, or logging? Is `endpoint_configured` true?
2. Check the OpenTelemetry **Collector** first — it's the fan-in for
   {Prometheus, Loki, Tempo, Sentry}. If the Collector is down or backed up, all four
   look broken. Restart/scale it; check its exporter queues.
3. Check the transport: `OTEL_EXPORTER_OTLP_ENDPOINT` reachable over the private
   network, TLS valid (never disable cert verification), and
   `OTEL_EXPORTER_OTLP_HEADERS` auth correct.
4. For Prometheus specifically: confirm the scrape can reach `/internal/metrics` and
   presents the bearer token (`PROMETHEUS_METRICS_TOKEN`) or comes from the trusted/
   loopback network — a 403 here means auth/network, not app failure.
5. Because failure mode is `degrade`, exporters self-recover when the backend returns;
   no app restart is required for telemetry to resume once the pipe is healthy.

## Escalation criteria

- Observability down during another active incident (compounding blindness) —
  prioritize restoring at least metrics + logs.
- Sustained export failures > 30 min, or data loss beyond retention windows.
- Any indication the Collector/obs server is unreachable due to a network/firewall
  change — pull in infra/networking.

## Recovery verification

- `petabyte_telemetry_export_failures_total` stops incrementing.
- `/health/observability` shows `tracing.active=true` and `metrics.active=true`.
- New traces appear in Tempo, series resume in Prometheus, and log lines flow in Loki.
- Sentry is **optional**: only if Sentry is enabled **and** `SENTRY_DSN` is configured,
  confirm a test error reaches Sentry. If Sentry is not configured, skip this check and
  instead verify the telemetry backends that *are* configured (Prometheus / Loki /
  Tempo) have recovered.
- Grafana dashboards repopulate with current data.

## Financial-safety considerations

- Telemetry carries **no** financial authority. Even total loss of Loki/Tempo/
  Prometheus/Sentry does not affect money movement — the durable record is Postgres.
- **Never** make the telemetry path blocking to "not miss data"
  (`OBSERVABILITY_FAILURE_MODE=strict` in production would let a telemetry outage break
  requests) — keep `degrade` in production.
- Do not treat missing dashboard data as a settlement problem; verify financial state
  against Postgres / the transaction timeline, not against telemetry gaps.
- Redaction runs before export; if the pipeline is misconfigured, never "work around"
  it by disabling `LOG_REDACTION_ENABLED` — that risks leaking secrets/PII into logs.
