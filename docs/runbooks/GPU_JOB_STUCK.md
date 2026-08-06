# Runbook: GPU Job Stuck

A job dispatched to a GPU is not progressing: it started but never reaches
completion/validation, or it sits in `RUNNING` far beyond expected duration.

## Symptoms

- A transaction stuck in `RUNNING` (or `DISPATCHING`) well past the template's
  expected runtime and past `NB_TIMEOUT` / `PLATFORM_MAX_DURATION_S` bounds.
- `job.execution.started` logged but no `job.execution.completed` /
  `job.execution.failed` follows.
- `petabyte_job_duration_seconds` outliers; a specific `gpu_class` skewing high.
- Buyer reports a hung/silent job.

## Impact

- Buyer's GPU is held and their authorization ages toward expiry.
- Seller capacity is tied up on a job that may never settle.
- If the container is genuinely wedged, metering could over- or under-count usage if
  not finalized correctly.

## Dashboard

**Transaction Trace** (single-job forensics) and **Seller-Agent Fleet** (node/GPU
health).

## Loki query

```logql
{service="petabyte-api"} | json | transaction_id="<TX>"
```

Then follow the job across services (executor lives on the seller node):

```logql
{service="petabyte-gpu-executor"} | json | job_id="<JOB_ID>"
{environment="production"} | json | job_id="<JOB_ID>" | event_name=~"job.*"
```

## Metrics to inspect

- `petabyte_job_duration_seconds` (are durations abnormal for this class?):
  ```promql
  histogram_quantile(0.95, sum by (le,gpu_class) (rate(petabyte_job_duration_seconds_bucket{environment="production"}[30m])))
  ```
- `petabyte_jobs_total{job_status="running"}`-adjacent gauge `petabyte_jobs_running`
  vs. capacity.
- GPU health via DCGM: `DCGM_FI_DEV_GPU_UTIL` (is it doing work or hung at 0?),
  `DCGM_FI_DEV_GPU_TEMP`, `DCGM_FI_DEV_XID_ERRORS`:
  ```promql
  increase(DCGM_FI_DEV_XID_ERRORS[15m]) > 0
  ```

## Trace to inspect

1. From the transaction Loki query, read the `trace_id`.
2. Open in **Tempo** (or paste into the **Transaction Trace** dashboard).
3. Walk the spans: last successful step (`job.dispatched` → `job.execution.started`)
   and where it hangs. A missing child span for result upload/validation means the job
   never got that far. XID errors on the span/host point at a GPU fault, not a
   platform bug.

## Safe first actions

1. Distinguish "slow but alive" from "wedged": `DCGM_FI_DEV_GPU_UTIL` > 0 and rising
   `petabyte_job_duration_seconds` → likely just a long job; verify against the
   template's expected runtime and `NB_TIMEOUT`.
2. If genuinely hung, let the platform's timeout/reaper drive it to
   `job.execution.failed` → `JOB_FAILED`. The per-cell/`NB_TIMEOUT` and
   `PLATFORM_MAX_DURATION_S` bounds exist precisely to prevent unbounded holds.
3. If the GPU shows XID/thermal faults, the node is the problem — see
   `SELLER_AGENT_OFFLINE.md`; the job should fail and refund.
4. Do not hand-transition to `METERING_FINALIZED`/`PAYMENT_CAPTURED` to "close it
   out" — metering must reflect real delivered usage.

## Escalation criteria

- Job wedged and the timeout is not firing (reaper stuck — check `/health/ready`
  `maintenance.stale`).
- Repeated stuck jobs on the same template or `gpu_class` (systemic bug or bad node).
- Any case where you're tempted to finalize metering manually — escalate instead.

## Recovery verification

- The job reaches a terminal state: completed+validated → settled, or failed →
  refunded. Confirm on `/payments/{id}/timeline`.
- `petabyte_job_duration_seconds` outliers stop for that class/template.
- The GPU returns to available supply (`petabyte_gpus_available`).

## Financial-safety considerations

- Capture must reflect **metered actual usage** (`settlement.metering.finalized`),
  never the up-front estimate. A stuck job that produced no validated result should
  refund, not capture.
- If partial usage was genuinely delivered and metered before the hang, the FSM path
  is `RUNNING → METERING_FINALIZED → PAYMENT_CAPTURE_PENDING` for the metered amount
  only. When in doubt, refund — a buyer must not pay for a hung job.
- Seller payout follows buyer capture; a stuck job never triggers a premature transfer.
