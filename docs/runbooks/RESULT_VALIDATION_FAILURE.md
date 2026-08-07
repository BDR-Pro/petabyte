# Runbook: Result Validation Failure

The result validator (`petabyte-result-validator`) is rejecting job results, or
failing to validate them. Validation gates settlement: a result that does not pass
should not be captured against the buyer as a successful, billable job.

## Symptoms

- Rising `event_name="result.validation.failed"` relative to
  `result.validation.passed`.
- Jobs terminating as `invalid` rather than `validated`.
- Buyers report "job ran but was marked failed/invalid".
- Grafana alert `ResultValidationFailureRateHigh` firing.

## Impact

- Legitimate jobs failing validation → unnecessary refunds and buyer friction.
- Or (the fraud case) genuinely invalid/incomplete results being caught — working as
  intended, protecting buyers from paying for junk output.
- Distinguishing the two is the whole job of this runbook.

## Dashboard

**Transaction Trace** (per-job) and **Executive Marketplace** (validation pass/fail
trend, reliability).

## Loki query

```logql
{service="petabyte-result-validator"} | json | event_name=~"result.validation.(passed|failed)"
```

Drill into one job/transaction:

```logql
{service="petabyte-result-validator"} | json | job_id="<JOB_ID>"
{service="petabyte-api"} | json | transaction_id="<TX>"
```

## Metrics to inspect

- Validation failure share (validator writes terminal job status):
  ```promql
  sum(rate(petabyte_jobs_total{job_status="invalid",environment="production"}[15m]))
  /
  sum(rate(petabyte_jobs_total{job_status=~"validated|invalid",environment="production"}[15m]))
  ```
- Break down by `template` and `gpu_class` to spot a bad template or a bad node class:
  ```promql
  sum by (template,gpu_class) (increase(petabyte_jobs_total{job_status="invalid",environment="production"}[1h]))
  ```
- Correlate with GPU faults (`DCGM_FI_DEV_XID_ERRORS`) — hardware errors can corrupt
  results.

## Trace to inspect

1. Take a failing `job_id`/`transaction_id` from Loki.
2. Read the `trace_id`; open in **Tempo** or the **Transaction Trace** dashboard.
3. Follow `result.uploaded` → `result.validation.failed`. The validator span carries
   the failure reason (e.g. matmul check mismatch, missing output, timeout). Confirm
   whether the failure is deterministic content (bad result) or infrastructure
   (upload/validator error).

## Safe first actions

1. Classify the failure:
   - **Content mismatch** (result doesn't match expected / matmul verification fails):
     the validator is doing its job; the job should fail → refund. If it clusters on
     one seller/node, that's a seller-quality/fraud signal (see `SELLER_ANTIFRAUD`).
   - **Validator-side error** (validator crashing, timing out, can't fetch the
     result): this is an infra bug — do **not** let it mass-fail good jobs.
2. If the validator itself is broken, check its process/health and recent deploys;
   roll back if a validator change caused it.
3. Concentrate on `template` / `gpu_class` clustering to isolate a bad template vs. a
   bad node vs. a validator regression.

## Escalation criteria

- Validator-side errors causing broad false negatives (good jobs marked invalid) —
  this wrongly denies sellers payment and must be stopped fast.
- A single seller/node with an anomalous invalid rate (possible fraud) — route to the
  anti-fraud owner.
- Validation logic change under suspicion — page the settlement/validation owner.

## Recovery verification

- `result.validation.passed` / `failed` ratio back to baseline.
- `petabyte_jobs_total{job_status="invalid"}` returns to normal.
- Re-run/spot-check a known-good job through validation.

## Financial-safety considerations

- Validation is a **capture gate**. A failed validation must lead to refund, not
  capture — the buyer does not pay for an unvalidated/incorrect result.
- Never override a validation failure to force capture without a verified, documented
  reason; that would charge a buyer for output the platform could not verify.
- A validator outage that would otherwise mass-fail jobs should hold settlement
  (leave transactions pre-capture) rather than auto-refund or auto-capture blindly —
  escalate so real results aren't discarded and buyers aren't wrongly charged.
