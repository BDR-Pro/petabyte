# Seller Onboarding (Stripe Connect)

A seller must complete Stripe Connect onboarding before they can offer **paid** GPU
supply. Petabyte does not build custom KYC — Stripe collects identity, business and
payout details via hosted onboarding.

## What is tracked (`ConnectedAccount`)

Connected account id, country, default currency, onboarding state, details-submitted,
charges-enabled, payouts-enabled, transfers capability, card-payments capability,
requirements currently due, requirements past due, disabled reason, last-sync time.

**Payout-ready** (`ConnectedAccount.payout_ready()`) requires `charges_enabled` AND
`payouts_enabled` AND `transfers` capability `active`. `details_submitted` alone is
**not** enough. A seller cannot list paid supply until payout-ready.

## Flow

```mermaid
sequenceDiagram
    participant Se as Seller
    participant P as Petabyte
    participant S as Stripe
    Se->>P: POST /payments/connect/account
    P->>S: Account.create (Express, card_payments+transfers) [idem petabyte:account:{uid}]
    S-->>P: acct_...
    P-->>Se: connected_account_id
    Se->>P: POST /payments/connect/onboarding-link
    P->>S: AccountLink.create (onboarding)
    S-->>P: hosted URL
    P-->>Se: redirect to Stripe
    Se->>S: complete identity / bank details
    S-->>P: webhook account.updated (authoritative)
    P->>S: Account.retrieve (on return + on webhook)
    P->>P: sync capabilities/requirements; set payout_ready
    Note over P: return URL alone NEVER marks onboarding complete
```

## Status endpoint

`GET /payments/connect/status` returns the full readiness set plus a human
`why_blocked` explanation, e.g. *"Finish Stripe onboarding. Payouts capability not
active yet. Stripe needs: external_account, tos_acceptance.date."* The seller
earnings page renders these states: connect account, onboarding in progress,
information required, verification pending, payouts enabled, payouts restricted,
account disabled, plus a "Return to Stripe onboarding" and (where supported) an
"Open Stripe dashboard" link.

## Authoritative sync — never trust the return URL

After the seller returns from Stripe, Petabyte retrieves the account **server-side**
(`refresh_connected_account`) and also processes the `account.updated` webhook. Only
those authoritative signals flip `payout_ready` and re-enable paid supply.

## Idempotency & isolation

- One connected account per seller (`get_or_create_connected_account`); a repeat call
  returns the same account and never creates a second Stripe account.
- A seller can only ever create/read their **own** account (the endpoint keys on the
  authenticated user); there is no way to substitute another seller's connected
  account id.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/payments/connect/account` | Create/return this seller's connected account |
| POST | `/payments/connect/onboarding-link` | Hosted onboarding link |
| POST | `/payments/connect/refresh` | Authoritative status pull from Stripe |
| GET | `/payments/connect/status` | Readiness + why-blocked |
| GET | `/seller/earnings/stripe` | Gross / commission / net / transfers + payout events |
