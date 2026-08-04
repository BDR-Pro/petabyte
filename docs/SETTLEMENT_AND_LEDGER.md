# Settlement & Ledger

## Fee rule (documented default; configurable; snapshotted per transaction)

- Buyer pays the final **compute** amount = price × ACTUAL metered usage (≥ min charge).
- Platform commission = `commission_bps`/10000 × captured (+ optional fixed fee),
  floored so it never exceeds the captured amount.
- Seller net = captured − commission.
- The **Stripe processing fee is borne by the platform** (the charge lives on the
  platform account) and is tracked **separately** (`stripe_fee_amount`), never taken
  from the seller.

Identity, always, in integer minor units:

```
captured_amount == platform_fee_amount + seller_net_amount
```

Config (`pricing.PricingConfig`, env-driven): `PLATFORM_COMMISSION_BPS`
(default = `PLATFORM_TAKE_RATE`), `PLATFORM_FIXED_FEE_MINOR`, `PLATFORM_CURRENCY`,
`PLATFORM_MIN_CHARGE_MINOR`, `PLATFORM_MAX_DURATION_S`, `PLATFORM_AUTH_MARGIN_BPS`.
A **pricing snapshot** is frozen onto every transaction at authorize time, so a later
config or price change never rewrites a historical charge.

## Worked examples (USD, cents)

Assume $2.50/hr = 250 minor/hr, 10% commission, 20% auth margin, min charge 50.

| Scenario | Metered | Captured | Platform fee | Seller net | Stripe fee (sep.) |
|---|---|---|---|---|---|
| 1h estimate, 30m used | 1800s | 125 | 12 | 113 | tracked separately |
| 1h estimate, full 1h | 3600s | 250 | 25 | 225 | tracked separately |
| 2m used (< min) | 120s | 50 (min) | 5 | 45 | — |
| 0s used | 0 | 0 (cancel, $0) | 0 | 0 | — |
| authorized 300, ran 90m | 5400s | 300 (capped at auth) | 30 | 270 | — |

Rounding: commission uses integer floor division on the captured amount, so the fee
never rounds above the capture and the identity holds exactly.

## Transfer (separate charges & transfers)

```mermaid
sequenceDiagram
    participant P as Petabyte
    participant S as Stripe
    Note over P: PAYMENT_CAPTURED (captured=125, fee=12, net=113)
    P->>P: guard: transfer only after capture; only if no stripe_transfer_id
    P->>S: Transfer net=113 -> connected acct [idem petabyte:transfer:{tx}:{v}]
    S-->>P: tr_...
    P->>P: ledger DEBIT seller_payable 113; CREDIT external:stripe_transfers 113
    P->>P: SELLER_TRANSFERRED -> COMPLETED; reconciliation=reconciled
```

The transfer never exceeds the captured amount, the settled seller amount, or the
amount not already transferred. It happens **at most once**, guarded by the unique
`PaymentOperation` key + `tx.stripe_transfer_id` + amount guard — safe across retries,
worker crashes, duplicate webhooks, admin retries, and concurrent workers.

## The internal ledger

Reuses the existing append-only double-entry ledger (`db.post`, `LedgerTx`,
`LedgerEntry`). Rules enforced: every transaction balances (debits == credits) or the
write is refused; unique external references (`idempotency_key` is UNIQUE); no
floating-point money; finalized entries are never edited — refunds and reversals
create **compensating** entries. `ledger_is_balanced()` reconciles the whole book.

Account map and postings are listed in
[STRIPE_CONNECT_ARCHITECTURE](STRIPE_CONNECT_ARCHITECTURE.md#ledger-accounts-double-entry-reused).

## Settlement versioning

`Settlement` rows are immutable and versioned. A refund/reversal advances the picture
by writing a new state, not by editing old rows. `settlement_version` is embedded in
capture/transfer idempotency keys so a *new* settlement can legitimately act while a
*repeat* of the same one cannot.

## Transfer vs bank payout (different events)

A successful Connect **Transfer** moves money to the seller's Stripe balance. It is
**not** a bank payout. Stripe pays the connected account's bank on the account's own
schedule, surfaced via `payout.created/updated/paid/failed` webhooks. The seller
dashboard shows both statuses distinctly and never claims "paid to bank" merely
because a transfer succeeded.
