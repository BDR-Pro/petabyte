# Data Flow

How data and money move through Petabyte, end to end, with the exact endpoints and
DB writes at each step. Everything below is implemented in `lumaris_api/`.

## 1. Seller onboarding → verified supply

| Step | Endpoint / action | State written |
|---|---|---|
| Create account | `POST /register_user` → `POST /login` | `User` |
| Become a seller | `POST /change_role {role:"seller"}` | `User.role` |
| List hardware | `POST /register_specs` | `SellerSpec` (trust: `self_reported`) |
| Prove hardware | `POST /prove` (Ed25519 over the spec) | `SellerSpec.attested=true`, `attest_pubkey` (trust: `agent_verified`) |
| Mint node key | `POST /create_api_key` | `IssuedKey` (scoped, revocable) |
| Come online | `POST /heartbeat` (X-API-KEY, X-Forwarded-For) | `status=online`, `last_seen`, region verified via GeoIP |
| (optional) benchmark | `POST /benchmark` → agent runs → `POST /jobs/benchmark_result` (signed) | `benchmark_tokens_sec` (trust: `benchmark_verified`) |

The seller sees exactly why they are or aren't earning at `/seller/dashboard`
(online? attested? priced above market? all units busy?) with the fix for each.

## 2. Buyer discovery → routing

| Step | Endpoint | Data |
|---|---|---|
| Browse | `GET /marketplace/specs` (public, no PII) | model, VRAM, price, per-class cloud reference, trust level, region, reliability, availability |
| Detail | `GET /marketplace/specs/{public_id}` | full spec, trust evidence + limits, protection terms |
| Route | `POST /solve` or `POST /launch` | eligible candidates gathered → scored (reputation/price/throughput, deterministic tie-breaks) → selected |
| Audit | `RoutingDecision` row written | intent, every candidate's factor scores, selection, plain-language explanation |

## 3. Booking → escrow (money in)

`POST /request_vm` (or `/launch`):
1. Validate spec: attested, online, not own, trust/region constraints.
2. `try_reserve_unit` — atomic capacity decrement (prevents oversell under races).
3. Kill-switch check (`bookings_are_paused`).
4. `try_debit` — atomic buyer/org wallet debit.
5. `book_with_escrow` — `Booking` row + ledger postings: buyer_available → `escrow:{id}`.

Idempotency: an `Idempotency-Key` header claims a slot before any side effect;
replays return the stored response. On any failure the unit is released and funds
returned (compensating actions), then the error is reported.

Ledger legs (booking):
```
DEBIT  buyer_available:{buyer}   gross
CREDIT escrow:{booking}          gross
```

## 4. Job execution

| Step | Endpoint | Notes |
|---|---|---|
| Submit | `POST /create_task` | `Task` (pending); `booking` → active |
| Claim | `GET /jobs/next` (X-API-KEY) | ownership-scoped; `Task` → running |
| Run | (agent, in Docker) | sandboxed; no host fallback |
| Report | `POST /jobs/result` (signed) | Ed25519 sig verified against the attested key |

## 5. Settlement (money out to earnings)

On `completed`, `release_booking` (idempotent) posts:
```
DEBIT  escrow:{booking}          gross
CREDIT seller_earnings:{seller}  gross - fee
CREDIT platform_revenue          fee
```
Metered rentals (`settle_metered`, `stop_vm_metered`) bill only hours held and
refund the remainder. Node death is handled by the reaper: `reap_and_failover`
migrates the VM to another node (same stable address) or `settle_dead_specs` refunds.

## 6. Payout (money to the seller's bank / USDC / gift card)

| Step | Endpoint / worker | State |
|---|---|---|
| Add destination | `POST /wallet/payout-method` | `SellerPayoutMethod` (24h cooling-off) |
| Request | `POST /wallet/withdraw` | screen() (fail-closed in live) → `Payout` (requested) |
| Send | `tools/payout_worker.py` → `process_payouts` | provider `.send` → confirmed/failed |
| Schedule | `POST /wallet/schedule` | `PayoutSchedule` (weekly) |

Ledger legs (payout): `DEBIT seller_earnings → CREDIT external:payouts`. Failure
reverses. The worker has no scheduler in deploy today (see PRODUCTION_GAPS); payouts
run in sandbox by default (`PAYOUT_STUB=true`).

## 7. Receipts & audit

- Buyer: `GET /bookings/{id}` (status, price, fee, seller payout, routing explanation),
  `GET /routing/decisions/{id}` (full placement audit).
- Seller: `GET /seller/earnings`, `GET /seller/dashboard` (utilization + blockers).
- Admin: `GET /admin/overview`, `/admin/audit` (append-only who-did-what),
  `/admin/payouts`, `/admin/bookings/pause` (kill switch).
- Platform: `GET /metrics/overview` (GMV, take rate, utilization, savings, reliability;
  demo/real separated; ledger-balanced integrity signal).

## Money invariant

Across all of the above the books always balance: `ledger_is_balanced` returns true
and every account balance reconstructs from the ledger. `adversarial_test.py` proves
`deposits == wallets + earnings + platform + escrow` after concurrent abuse, and that
the ledger refuses any unbalanced transaction.
