# Diligence & release evidence

Petabyte's release bar is a **command**, not a claim. Instead of "all tests passed", a
release is traceable to a machine-readable evidence bundle that records exactly what ran,
on which commit, with which result.

```bash
make verify-series-a          # full run; writes evidence/series-a-<sha>.json + evidence/latest.json
make verify-series-a ARGS='--quick'    # fast structural gates only
make verify-series-a ARGS='--strict'   # P0 skips (e.g. Postgres) count as failures too
python scripts/verify_series_a.py --only drift,financial_audit,stripe
```

The bundle is written to `evidence/` (git-ignored — it is generated, and changes every run;
attach it to a release/PR or a data room rather than committing it).

## What the bundle contains

- `commit`, `branch`, `dirty` — provenance of exactly what was verified.
- `summary` — P0/P1/signal pass/fail/skip counts.
- `release_ready` — **true only when every P0 gate actually PASSED**. A skip is not a pass:
  if the Postgres-only invariants didn't run (no Postgres `DATABASE_URL`), `release_ready`
  is false with a caveat, even if nothing failed.
- `caveats` — P0 gates that were skipped and why (so nobody mistakes "not run" for "passed").
- `gates[]` — per-gate id, priority, status, exit code, duration, and a short detail tail.

## The gates

| Priority | Meaning | On failure |
|---|---|---|
| **P0** | Release-blocking: money correctness, security, config integrity, schema, drift. | Command exits non-zero; `release_ready=false`. |
| **P1** | Should pass: UX/support suites, agent telemetry, local E2E. | Recorded; does not by itself set the exit code. |
| **signal** | Informational: `ruff`, `pip-audit`, honest payout-coverage shortfall. | Never blocks. |

P0 gates include: clean-DB schema build, config drift, manifest/docs freshness,
dashboard/alert/workflow validity, **ledger integrity + booking/payout reconciliation**
(`audit_ledger`), a best-effort secret scan, the smoke/adversarial/**Stripe**/payout/config/
env-vars/observability/marketplace suites, and the **Postgres-only invariants**
(exact NUMERIC, advisory-lock leader election, real write races) — which must be run with a
Postgres `DATABASE_URL` (CI) to fully meet the bar; they are skipped honestly on SQLite.

Authoritative secret scanning remains **gitleaks in CI**; the in-command `secret_scan` is a
fast local backstop, not a replacement.

## The Series-A technical bar (#500)

A release meets the bar when:

- zero known **P0** financial/security defects (all P0 gates pass, none merely skipped);
- all P1 risks are owned or mitigated (tracked, not living in someone's memory);
- deploys are reproducible and roll back cleanly;
- recovery is tested (failover, restore, worker/lease recovery);
- real-money reconciliation holds (internal ledger ↔ provider);
- the seller sandbox is hardened and adversarially tested on a real GPU host;
- SLOs are measurable and observability proves the money path end to end;
- the platform scales without depending on undocumented manual intervention.

`make verify-series-a --strict` under CI Postgres is the automatable slice of that bar; the
remaining items (recovery drills, on-GPU sandbox escape tests, restore evidence, load
results) are captured alongside the bundle in this directory as they are produced.
