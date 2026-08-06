# Preventing seller-side scams

Sellers run on hardware Petabyte doesn't control, so the platform treats every seller as
adversarial and **verifies** two things independently: (1) that the seller actually
delivers the GPU they sold, and (2) that the results they return are genuine, not
corrupted or faked. The rule that ties it together: **money is captured from the buyer at
completion, but the seller is paid only after the work survives verification and a hold
window** (see `docs/PAYOUT_HOLD_AND_SCHEDULE.md`).

## 1. Is the seller really delivering the GPU?

- **Hardware attestation.** A node registers a spec and attests it at `POST /prove` with
  an Ed25519 key; the pubkey is bound to the spec. Every later result must be signed by
  that same key, so results are cryptographically bound to the attested machine
  (`utils.verify_signed_proof`, `main.py` `/jobs/result`).
- **Liveness.** Heartbeats keep a spec `online`; the reaper marks stale nodes offline and
  fails a buyer over to another node / refunds — a seller can't be paid for a node that
  went dark mid-job.
- **Random spot-check audits ("proof of continuous honest compute").** The platform
  randomly injects **server-seeded known-answer challenges** into live, bookable sellers
  (`seller_audit.run_spot_checks`, `POST /admin/audits/run`, scheduled by cron). The
  answer is computed server-side; a seller who isn't really running work on the claimed
  GPU can't produce it. Failing an audit drops reputation **and freezes the seller's
  payouts** for review. Because audits are unannounced and indistinguishable from real
  jobs, a scammer can't tell which job is the test.
- **Capability floor (recommended next).** Before a spec is bookable, require an
  *attested benchmark* proving the GPU meets the advertised class (e.g. an H100 can't be
  served by a GTX 1060). The `benchmark` path exists; its harness is still a stub
  (`task_fetcher._run_benchmark`) — wiring a real one closes "listed an H100, served a
  potato."
- **Buyer dispute + report.** For interactive/VM rentals the buyer can report a seller
  (`POST /report/seller`); combined with the 14-day hold this freezes payout until an
  admin checks (`docs/PAYOUT_HOLD_AND_SCHEDULE.md`).

## 2. Is the result genuine (not corrupted or faked)?

Never trust a bare `completed=true`. Layered, from cheapest to strongest:

- **Signature binding.** The result carries a signed proof (`output_hash` + `ts`) verified
  against the attested key, with a replay window. A forged/expired signature is **hard
  fraud** → 401, reputation penalty, fraud recorded, **payouts frozen**.
- **Known-answer validation.** For `test` jobs the server compares the returned hash to
  the value it computed at dispatch (integer-deterministic, so it's reproducible across
  GPUs). Wrong answer on a platform audit → freeze.
- **Deterministic-job manifest validation** (`matmul_validation.py`, wired fail-closed for
  `pytorch-matmul-v1`): re-derives the canonical manifest hash, **binds the server nonce +
  seed** (so a result can't be precomputed or replayed), enforces a **container-digest
  allowlist**, **numeric tolerance** vs a reference, **runtime bounds** (too fast = didn't
  really run; over max = timeout), **GPU-telemetry consistency** (0% GPU utilisation →
  INCONCLUSIVE), and **duplicate-submission** detection. Verdict ∈
  `VALID/INVALID/INCONCLUSIVE/MANUAL_REVIEW`; a seller is paid **only on VALID**.
- **Redundant re-execution / quorum (implemented — `quorum.py`).** Dispatch the SAME
  seeded challenge to several independent sellers and compare their results
  (`POST /admin/quorum/run?replicas=N`). Seller agreement is the oracle, so it works even
  for workloads the platform can't compute itself:
    - **AGREED** — a majority returned the same result; any seller who diverges from it
      faked/corrupted the result → **frozen for fraud** (`seller_audit.freeze_for_fraud`).
    - **INCONCLUSIVE** — no majority (e.g. a 1-vs-1 split): we can't tell who's right →
      **all participants held** for manual review (never auto-paid).
  You need ≥3 replicas to identify a single liar; with 2 a disagreement holds both.
- **Signed result manifest + GPU binding (recommended next).** Have the agent include the
  GPU UUID/model/driver/CUDA in the signed manifest and check it against the attested spec;
  a class/perf mismatch is fraud.

## How detection connects to money (the part that makes it bite)

- **Capture ≠ payout.** The buyer is charged at completion, but the seller's net becomes a
  **held obligation** for `PAYOUT_HOLD_DAYS` (14). Nothing is disbursed during the window.
- **Fraud → freeze.** `seller_audit.freeze_for_fraud` (called on forged signature, failed
  platform audit, or an invalid result) records the fraud, penalizes reputation (which can
  drop the seller below the `can_accept_paid_jobs` gate), and **places a payout hold** so
  matured earnings are not batched until an admin clears it.
- **Reputation gate.** Repeated failures push reputation below `MIN_REPUTATION` → the
  seller is delisted from the marketplace and can take no new paid work.
- **Biweekly batch respects holds.** The scheduled payout run skips held sellers, so
  frozen earnings never go out by accident.

## Economic hardening (recommended, not yet built)

- **Seller bond / stake** slashed on proven fraud — makes scamming cost more than it earns.
- **New-seller throttle**: lower limits + higher audit rate until a track record exists.
- **Anomaly detection**: sudden job spikes, implausibly uniform/fast completions, one
  destination across many "distinct" sellers.

## Config

- `SELLER_AUDIT_SAMPLE_RATE` (default 0.25) — fraction of live sellers spot-checked per run.
- `SELLER_FRAUD_PENALTY` (default 40) — reputation hit on hard fraud.
- `PAYOUT_HOLD_DAYS` (14), `PAYOUT_HOLD_ON_REPORT` (true), `MIN_REPUTATION` (50).

## Endpoints

- `POST /admin/audits/run?sample_rate=` — dispatch spot-check audits (cron this).
- `POST /report/seller` — buyer/anyone reports a seller (→ hold).
- `POST /admin/sellers/{u}/payout-hold` · `/payout-release` — manual freeze/clear.

## Tests

`seller_audit_test.py` (over HTTP, real agent crypto): a platform audit is dispatched to a
live seller; an honest correct answer passes with **no** freeze; a wrong answer to a
platform audit **freezes** payouts; a forged signature is rejected **and** freezes
payouts. Plus `matmul_validation_test.py` (result-integrity verdicts) and `stripe_test.py`
/ `payout_test.py` (hold + report + biweekly).
