# Refunds, Disputes & Reversals

Explicit behavior for every money-recovery path. A refund of a platform charge does
**not** automatically reverse a separate seller transfer — Petabyte handles both
sides and only marks the workflow reconciled when both are accounted for.

## Matrix

| Situation | What happens |
|---|---|
| Cancel before capture | `cancel_authorization`: PaymentIntent canceled, GPU released, buyer charged $0. |
| Full refund after capture, before transfer | Refund the charge; ledger returns funds from `platform_revenue` + `seller_payable`. No transfer existed. → `REFUNDED`. |
| Partial refund | Refund the requested amount; seller share clawed back **proportionally** (`pricing.refund_split`). Stays non-terminal until fully refunded. |
| Refund **after** transfer | Refund the charge **and** create a Stripe **transfer reversal** for the seller's proportional share; ledger posts a compensating reversal. |
| Transfer reversal fails | Refund is recorded, `reconciliation_status = needs_review`, escalated to admin — never silently marked done. |
| Dispute created | `charge.dispute.created` → tx `DISPUTED`, `reconciliation_status = needs_review`. |
| Dispute lost / closed | Handled via dispute webhooks; admin reconciles liability (platform bears the charge). |
| Insufficient platform balance / failed transfer | `TRANSFER_FAILED` (retryable); admin `retry transfer`. |
| Failed bank payout | `payout.failed` webhook recorded; surfaced on the seller dashboard as "payout failed" (distinct from transfer). |

Idempotency keys embed the settlement version and amount, so a repeated refund or
reversal request never double-moves money.

## Refund after transfer (with clawback)

```mermaid
sequenceDiagram
    participant A as Admin
    participant P as Petabyte
    participant S as Stripe
    Note over P: COMPLETED (captured=250, net=225, transfer tr_...)
    A->>P: POST /admin/payments/{id}/refund {amount:250, reason}
    P->>P: REFUND_PENDING; refund_split -> seller_reversal=225, platform_refund=25
    P->>S: Refund 250 on PaymentIntent [idem]
    S-->>P: refunded
    P->>P: ledger CREDIT external:payments:minor 250; DEBIT platform_revenue:minor 25 + seller_payable 225
    P->>S: Transfer reversal 225 on tr_... [idem]
    S-->>P: reversed
    P->>P: ledger DEBIT external:stripe_transfers 225; CREDIT seller_payable 225
    P->>P: refunded==captured -> REFUNDED; reconciled (or needs_review if reversal failed)
```

## Dispute

```mermaid
sequenceDiagram
    participant S as Stripe
    participant P as Petabyte
    participant A as Admin
    S-->>P: webhook charge.dispute.created
    P->>P: tx -> DISPUTED; reconciliation=needs_review
    A->>P: review in admin dashboard (evidence handled in Stripe)
    S-->>P: webhook charge.dispute.closed (won/lost)
    A->>P: reconcile liability; if lost, seller clawback via reversal if applicable
```

## Reconciliation state is independent of job state

`reconciliation_status` (`pending | reconciled | needs_review`) is tracked separately
from the customer-facing job state, so a completed job with an unresolved money issue
is never shown as fully settled.

## Admin recovery actions

All admin financial actions require authorization, a **reason**, are audited
(`AuditEvent`), validate current state, and are idempotent: `reserve`, `dispatch`,
`meter`, `capture`, `transfer`, `refund` (full/partial). Where automatic recovery is
impossible (e.g. reversal not permitted), the transaction is flagged `needs_review`
for manual handling rather than left in a false "done" state.
