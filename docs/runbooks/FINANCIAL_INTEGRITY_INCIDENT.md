# Runbook: Financial-integrity incident (ledger imbalance / duplicate payout / stalled settlement)

**Severity: P0.** Fires from `PetabyteLedgerUnbalancedHeartbeat`, `PetabyteLedgerImbalance`,
`PetabyteSettlementsStalled`, `PetabytePayoutBacklogAging`, or a suspected duplicate payout.

The governing rule for every step below: **preserve evidence and never blindly edit ledger
rows.** The ledger is append-only; corrections are compensating transactions, not UPDATEs.

## 1. Stop the bleeding (first 5 minutes)
- Engage the **kill switch** so no NEW bookings start: set `Platform.bookings_paused = true`
  (admin panel) — running rentals finish and settle normally.
- **Freeze payouts**: stop the biweekly payout worker/timer (`systemctl stop lumaris-payout*`
  or disable its schedule) so an ambiguous state cannot be paid out again.
- Do NOT restart services hoping it clears — you may destroy in-flight evidence.

## 2. Confirm and scope
- `GET /admin/financial-integrity` (admin token) → `{ok, ledger:{balanced,net_minor,
  imbalanced_tx}, payout_backlog}`. `ok:false` confirms an imbalance.
- Run the offline audit against a **read replica or a restored snapshot** (never a mutating
  session): `DATABASE_URL=<replica> python scripts/audit_ledger.py`. It lists the exact
  unbalanced tx ids, orphan entries, and any booking/payout that fails to reconcile.
- Identify `payment_mode` (TEST vs LIVE) from the offending rows. **Never** mix modes when
  reasoning about impact.

## 3. Diagnose by symptom
- **Ledger imbalance** (`imbalanced_tx > 0` / `net_minor != 0`): find the tx via
  `audit_ledger.py`; read every leg. Determine whether an entry was written single-sided
  (a bug bypassing `db.post`) or a leg is missing. Capture the rows (SELECT into an export).
- **Duplicate payout suspected**: reconcile internal obligations/batches against the
  provider's transaction IDs (`reconcile.py`, provider dashboard). A payout with no matching
  `PayoutObligation`/`PayoutBatch`, or two provider transfers for one obligation, is the
  signal. Use the provider's idempotency key + transfer group to correlate.
- **Settlements stalled** (`PetabyteSettlementsStalled`): the settlement worker likely died.
  Check its logs and the `PAYMENT_CAPTURED` transition rate; restart it AFTER confirming no
  half-committed capture is outstanding (query `PaymentOperation` state).
- **Payout backlog aging** (`PetabytePayoutBacklogAging`): the biweekly scheduler stalled;
  `petabyte_payout_obligations_unbatched` is growing. Check the worker/timer is installed
  and running; do not hand-run payouts until reconciliation is clean.

## 4. Correct (only after root cause is known)
- Fix the code path that produced the imbalance FIRST (so a correction is not immediately
  re-broken).
- Apply corrections as **compensating ledger transactions** via `db.post` (balanced legs),
  referencing the incident id in the description. Never `UPDATE`/`DELETE` historical rows.
- For a confirmed duplicate provider payout: recover via the provider (reversal) where
  possible, and record the reversal as a compensating transaction. Document the money delta.

## 5. Recover and verify
- Re-run `scripts/audit_ledger.py` → clean.
- `GET /admin/financial-integrity` → `ok:true`.
- Re-enable payouts, then lift the booking kill switch.
- Write a post-incident note: which tx, root cause, money delta, corrections applied, and
  the test/alert added so it cannot recur.

## Do NOT
- Do not edit or delete ledger rows.
- Do not retry a payment/refund/payout without first querying its durable operation identity
  and the provider (an ambiguous COMMIT/timeout may already have moved money — see
  reconciliation, and the crash-recovery invariants).
- Do not act across TEST and LIVE money in one operation.
