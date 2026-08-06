# Runbook: Seller Agent Offline

One or more `petabyte-seller-agent` nodes stopped heartbeating. Their GPUs drop out
of available supply; any job mid-flight on them is at risk.

## Symptoms

- `event_name="agent.heartbeat.missed"` in logs.
- `petabyte_agents_online` / `petabyte_gpus_online` drop.
- A node stops polling `/jobs/next` and stops posting `/heartbeat` (default heartbeat
  interval 15s; a silent node is reaped after `HEARTBEAT_TIMEOUT_S`, default 60s).
- Grafana alert `SellerAgentsDropped` / `GpusOnlineDropped` firing.

## Impact

- Reduced supply → potential `WORKER_QUEUE_BACKLOG.md`.
- Jobs actively running on a vanished agent may stall and eventually fail
  (`job.execution.failed`) → refund path; the buyer must not be charged for compute
  that did not complete.

## Dashboard

**Seller-Agent Fleet** (primary) and **Workers & Queue** (queue impact).

## Loki query

```logql
{service="petabyte-api"} | json | event_name="agent.heartbeat.missed"
```

Scope to a single node/GPU or job:

```logql
{service="petabyte-seller-agent"} | json | gpu_id="<GPU_ID>"
{service="petabyte-api"} | json | agent_id="<AGENT_ID>"
{service="petabyte-api"} | json | job_id="<JOB_ID>"
```

## Metrics to inspect

- Fleet size:
  ```promql
  petabyte_agents_online{environment="production"}
  petabyte_gpus_online{environment="production"}
  ```
- Sudden drop:
  ```promql
  delta(petabyte_gpus_online{environment="production"}[10m])
  ```
- GPU health from DCGM (per-node exporter): `DCGM_FI_DEV_XID_ERRORS`,
  `DCGM_FI_DEV_GPU_TEMP`, `DCGM_FI_DEV_GPU_UTIL` — an XID spike or thermal event often
  precedes an agent going dark:
  ```promql
  increase(DCGM_FI_DEV_XID_ERRORS[15m]) > 0
  ```
- Fallout on jobs:
  ```promql
  increase(petabyte_jobs_total{job_status="failed",environment="production"}[30m])
  ```

## Trace to inspect

1. Take a `job_id`/`transaction_id` that was running on the offline agent (from Loki).
2. Read the `trace_id`; open in **Tempo** or the **Transaction Trace** dashboard.
3. Confirm whether the job reached `job.execution.completed` before the agent dropped
   (safe to finish settling) or stalled after `job.execution.started` (must fail →
   refund).

## Safe first actions

1. Is it one node or many? A fleet-wide drop points at the platform side (API/network)
   rather than a seller's box — check `API_UNAVAILABLE.md` first if so.
2. For a single node: it self-recovers when the seller's machine/agent restarts
   (`agent.reconnected`); no platform action reserves its GPUs while offline (the
   reaper removes stale nodes from supply automatically).
3. For jobs stranded on the offline node: let them time out to
   `job.execution.failed` → the FSM drives `JOB_FAILED`/`REFUND_PENDING`. Do not
   manually mark them completed.
4. If DCGM shows XID/thermal faults, advise the seller; the node should not re-accept
   jobs until healthy.

## Escalation criteria

- Large simultaneous fleet drop (points at platform/network, not sellers).
- Stranded jobs not resolving to failure/refund within the expected timeout.
- Repeated flapping of the same node (heartbeat missed → reconnected) causing
  reservation churn.

## Recovery verification

- `petabyte_agents_online` / `petabyte_gpus_online` return to expected levels.
- `agent.reconnected` observed for recovered nodes.
- Any stranded job is either completed-and-settled or failed-and-refunded — none left
  in limbo. Confirm via the transaction timeline (`/payments/{id}/timeline`).

## Financial-safety considerations

- A buyer must never be charged for a job that did not produce a validated result.
  When an agent disappears mid-job, the correct terminal path is
  `JOB_FAILED → REFUND_PENDING → REFUNDED` (or, if usage was genuinely delivered and
  metered before the drop, capture only the metered amount — never the full estimate).
- Seller transfer happens **only after** buyer capture and at most once; an offline
  agent cannot cause a double payout.
- Do not release/refund by hand-editing DB state — drive it through the FSM so the
  append-only `ComputeTxEvent` history and ledger stay consistent.
