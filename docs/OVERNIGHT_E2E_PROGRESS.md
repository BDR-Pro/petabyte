# Overnight E2E — Progress / Restartable Checkpoint

Machine-readable twin: `artifacts/e2e-run-state.json`.
Full analysis: `docs/BUYER_SELLER_GPU_E2E_REPORT.md`.
Template audit: `docs/WORKLOAD_TEMPLATE_AUDIT.md`.

This run is **BLOCKED_EXTERNAL**: the live buyer→seller flow cannot execute from
this Claude Code session (no network to the Droplets/site/Stripe, no SSH
client/key, no GPU). All possible in-repo work was done instead. Nothing was
fabricated; no Stripe or GPU state was created.

---

## Checkpoint log

### 2026-08-05T21:34Z — Phase 1 (Baseline / reachability)
- Git commit at start: `4f85ad9`; branch `claude/petabyte-funding-readiness-fun2q6`.
- Platform health: **unknown** — `https://petabyte.market` → HTTP 403 at egress
  gateway (policy denial, confirmed with CA bundle).
- Seller-agent health: **unknown** — seller Droplet unreachable.
- Reachability probes (evidence in the report §2):
  - buyer/seller `:22` (SSH) → timeout; `ssh` client absent; `DEPLOY_SSH_KEY` absent.
  - Droplet `:443` and `petabyte.market` → intercepted by Anthropic egress gateway, 403.
  - Stripe keys absent; `nvidia-smi`/`torch` absent.
- **Checkpoint result:** live infra unreachable → `BLOCKED_EXTERNAL`. Pivot to
  all-possible in-repo work.

### 2026-08-05T21:34Z — Template + pipeline audit
- Wrote `docs/WORKLOAD_TEMPLATE_AUDIT.md` (12 container templates + 8 task types).
- Capability inventory (report §3–§4): money FSM is production-shaped and tested;
  compute/validation half is thin and not wired to the paid path; no matmul
  workload exists; benchmark harness is a stub; metering is admin-supplied.

### 2026-08-05T21:xxZ — Groundwork: result validator
- Added `lumaris_api/matmul_validation.py` + `matmul_validation_test.py`
  (offline-unit-tested `pytorch-matmul-v1` validator). Wired into `run_tests.sh`
  and CI. This is a tested component, **not** live-wired and **not** run against a
  real GPU manifest.

---

## Mandatory phases — status

| Phase | Status | Note |
|---|---|---|
| 1 Baseline | DONE (blocked) | infra unreachable; repo audited |
| 2 Infrastructure verification | BLOCKED_EXTERNAL | needs Droplet/site access |
| 3 Unpaid GPU diagnostic job | BLOCKED_EXTERNAL | needs seller GPU |
| 4 Stripe authorization | BLOCKED_EXTERNAL | needs Stripe keys + network |
| 5 Paid end-to-end job | BLOCKED_EXTERNAL + impl. gap | needs §4 report work + access |
| 6 Repeatability (2 runs) | NOT STARTED | depends on Phase 5 |
| 7 Failure testing | PARTIAL (offline only) | signature/idempotency covered by suite |
| 8 Restart recovery | BLOCKED_EXTERNAL | needs services |
| 9 Final proof bundle | PARTIAL | reports + state written; live evidence absent |

## Success thresholds — status (all live ones unmet, honestly)

- 2 consecutive STANDARD paid jobs — **0** (blocked)
- ≥1 SMOKE job — **0** (blocked)
- ≥1 failed-validation test — offline unit test present; **0 live**
- duplicate webhook / duplicate dispatch / GPU-offline / cancel-before-dispatch /
  restart-recovery — **0 live** (some covered by offline suite)
- no duplicate capture / transfer — enforced in code + offline tests; **not live-verified**
- all buyer-visible templates working-or-removed — **not satisfiable without GPU**
- no active payment stub — the benchmark harness is still a stub (report §4)

## Next action (for a run that HAS access)

1. Provide access (report §6, option A/B/C).
2. Implement the four §4 gaps (matmul workload + agent harness; agent→metering
   bridge; wire `matmul_validation.py` into `/jobs/result`; rewire the paid path
   through the ComputeTransaction FSM).
3. Run Phase 3 (unpaid diagnostic) → Phase 4 (Stripe authorize) → Phase 5 (paid)
   → Phase 6 (repeat ×2) → Phase 7 (failures) → Phase 9 (proof bundle).
4. Update `artifacts/e2e-run-state.json` after each phase; only set `SUCCEEDED`
   with evidence for every completion criterion.

## Cleanup / safety

- This run created no Droplet state, no containers, no Stripe objects, no test
  data. Nothing to clean up on the infra side.
- Droplets untouched; safe to power off from this run's perspective (see report
  header). Only the user should approve destroying them.
