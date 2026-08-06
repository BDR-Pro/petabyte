# Seller payouts: 14-day hold + biweekly batch

Sellers are **not** paid the instant a job finishes. Each job's net earning is **held
for a risk window** so a dispute or report can be reviewed, and matured earnings are
then paid **in one aggregated payout on a biweekly run** — "hold each job's earnings
for 14 days, then pay the accumulated total once."

## Lifecycle

```
job completes ─▶ buyer CAPTURED now ─▶ seller net becomes a HELD payout obligation
                                        state=accrued, risk_hold_until = now + 14d
        (14 days later, if no open report)
                 ─▶ obligation matures: accrued ─▶ available
        (biweekly run)
                 ─▶ ALL available obligations for a seller ─▶ ONE PayoutBatch ─▶ paid
```

- The **buyer is charged at job completion** (capture); their receipt shows the payment
  as completed. Only the **seller payout** is deferred.
- Earnings inside the hold show as `pending_minor` in `seller_balances`; matured but
  unpaid show as `available_minor`; in a batch as `in_transit_minor`; done as `paid_minor`.

## The 14-day hold

- Set on every obligation at capture (`stripe_connect._ensure_payout_obligation`):
  `risk_hold_until = now + PAYOUT_HOLD_DAYS` (default **14**), max'd with any
  newly-added-destination cooling-off (`PAYOUT_COOLING_OFF_H`).
- Maturation is automatic and idempotent (`db.promote_due_obligations`): an accrued
  obligation flips to `available` once `available_at <= now` — **unless the seller is
  under an active report/payout hold**, in which case it stays held until released.
- Config: `PAYOUT_HOLD_DAYS=14` (0 disables the hold).

## Reports → payout hold

- Anyone signed in can **report a seller**: `POST /report/seller`
  `{ "seller": "<username or GPU public_id>", "reason": "..." }`. It records the report,
  emails the founder inbox (`ADMIN_USERS`, e.g. `info@petabyte.market`), and — when
  `PAYOUT_HOLD_ON_REPORT=true` (default) — places the seller's payouts **on hold**.
- While on hold, the seller's matured earnings are **not** batched (they stay pending),
  so nothing is disbursed while the report is checked.
- Admin review:
  - `POST /admin/sellers/{username}/payout-hold`   (hold, with a reason)
  - `POST /admin/sellers/{username}/payout-release` (release after checking)
- Holds are recorded as `risk` `ComplianceDecision` rows (audited, same decision log).
- Note: auto-hold-on-report is convenient but abusable (a bad-faith report freezes a
  seller's pending balance until an admin releases). It only affects **future**
  maturation, never already-paid funds; releasing is one admin call. Tighten later by
  requiring the reporter to have transacted with the seller if abuse appears.

## The biweekly run

- `payout_routing.run_scheduled_payouts(db)` matures due obligations (hold-aware), then
  for each seller with available earnings aggregates them into **one** `PayoutBatch` and
  sends it on the selected rail. Idempotent per obligation set (a re-run the same day
  pays nothing already paid).
- Run it every two weeks via cron/systemd — e.g. the 1st and 15th at noon UTC:

  ```
  0 12 1,15 * *  cd /opt/petabyte && python scripts/run_biweekly_payouts.py
  ```

- On demand (admin): `POST /admin/payouts/run`.
- Rail selection still enforces the existing guarantees: sanctioned countries blocked,
  an APPROVED current compliance decision required (fail closed), stablecoin only with
  consent, and one obligation paid by at most one batch. Until a seller's country has a
  real, approved, implemented rail (coverage is honestly 0 today), the run creates no
  batch for them and the earnings stay `available` for a later run — no fake payout.

## What changed

- `settle_after_result` now stops at **PAYMENT_CAPTURED** (buyer charged) and no longer
  transfers immediately; the seller net is a held obligation. The immediate
  `transfer_to_seller` remains available to admins as a manual override.
- The tx's buyer-side terminal state under this model is `PAYMENT_CAPTURED`; the seller
  payout is tracked by the obligation lifecycle (accrued → available → batched → paid).

## Tests

- `stripe_test.py` — capture-holds-not-transfers, held obligation created, not available
  before the hold, auto-promoted after, and withheld while under report / released after.
- `payout_test.py` — the biweekly run pays nothing inside the hold, withholds a reported
  seller after maturity, pays the accumulated total in ONE batch after release, and
  doesn't double-pay on a re-run.
- `scripts/e2e/local_e2e.py` — end-to-end over HTTP: job completes → buyer captured →
  seller payout held → biweekly run pays 0 inside the hold → buyer report holds payouts →
  admin releases.
