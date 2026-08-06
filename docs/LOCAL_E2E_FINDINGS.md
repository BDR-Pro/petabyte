# Local buyer→seller E2E (in-sandbox) — run + findings

`scripts/e2e/local_e2e.py` runs the **whole platform locally** and drives a real
buyer→seller→settlement flow through it, tracing bugs. Everything is in-process
to the sandbox — no Droplets, no real Stripe, no GPU:

- the real API as a **uvicorn server** on `127.0.0.1:8099` (SQLite + fake Stripe gateway),
- a **seller** actor that registers a spec, **attests it and signs job results with
  the agent's real Ed25519 crypto** (`lumaris_agent/crypto.py`), heartbeats, and
  completes Stripe Connect onboarding via a genuinely-signed `account.updated` webhook,
- a **buyer** actor that walks quote → authorize → card-confirm → reserve → dispatch,
- an **admin** actor that finalises metering → capture → seller transfer.

Run it:

```
make local-e2e            # or: python scripts/e2e/local_e2e.py
```

Exit code is non-zero if any step behaved unexpectedly. The final run is **green**:
the full flow reaches `COMPLETED` (captured = metered amount, `reconciliation_status
= reconciled`), and the known-answer test workload validates (`test_passed`).

```
seller: register spec → /prove (Ed25519) → heartbeat → Connect onboarding (payout_ready)
buyer:  quote → authorize (manual-capture PI) → confirm card → reserve → dispatch (RUNNING)
seller: /jobs/next → run → POST /jobs/result (signed) → completed
admin:  meter → capture (PAYMENT_CAPTURED) → transfer (SELLER_TRANSFERRED → COMPLETED)
```

## Findings traced while getting there

Each of these was hit by actually running the flow, not by reading code.

1. **No server-side path for card confirmation (blocked headless/offline E2E).**
   `/payments/authorize` creates a manual-capture PaymentIntent in
   `requires_payment_method`; moving it to `requires_capture` normally happens
   client-side via Stripe.js, so an API-only / CI run could never reach reserve or
   dispatch. **Fix:** added `POST /payments/{id}/simulate-card`, active **only** when
   the in-process fake gateway is used (returns 404 in real Stripe mode, so it is
   inert in production). This unlocks a full offline paid E2E — useful for CI, not
   just this harness.

2. **Starting Stripe Connect but not finishing removes the seller's GPU from the
   marketplace.** Before creating a connected account the spec was listed; after
   creating one (still `restricted`, `payout_ready=false`) the spec **disappeared**
   from `/marketplace/specs`, because `can_accept_paid_jobs` is gated to
   `payout_ready`. It reappears once onboarding completes. This is defensible (you
   can't sell if you can't be paid) but it's a sharp edge: a seller who clicks
   "set up payouts" and stops is silently delisted. Recommend surfacing a
   "finish onboarding to stay listed" state to the seller rather than a silent drop.

3. **Job completion did NOT auto-settle the payment ("two systems"). — FIXED.**
   Originally, `POST /jobs/result` for a paid, ComputeTransaction-dispatched job
   returned `booking_released: false` and did **not** drive the ComputeTransaction
   to metering/capture; settlement only happened via the **admin** endpoints. This
   was the central gap for a hands-off paid flow (`docs/REMOVED_PAYMENT_STUBS.md`,
   "the central rewire … not done").
   **Fix:** `/jobs/result` now calls the orchestrator bridge
   `stripe_connect.settle_after_result(tx, metered_seconds=…)` on a completed,
   signature-verified job — it finalises metering and drives capture + seller
   transfer through the **same audited functions** the admin endpoints use, so a
   completed job now reaches `COMPLETED` on its own. It is:
   - **fail-closed** — templates whose correctness needs manifest validation
     (`pytorch-matmul-v1`) are skipped until that validator is wired into the result
     payload, and a non-payout-ready seller can't even start a paid tx;
   - **idempotent + FSM-guarded** — a duplicate result or a concurrent admin call
     never double-charges or double-pays (verified: after auto-settle, an admin
     capture/transfer is a safe no-op);
   - **opt-out** via `AUTO_SETTLE_ON_RESULT=false` (settlement stays admin-driven).
   Metering uses platform-observed wall-clock (server-side), capped by the pricing
   snapshot's max duration.
   **Update — payout hold + biweekly batch:** the bridge now stops at
   `PAYMENT_CAPTURED` (buyer charged) and the seller's net is **held for 14 days**
   (`PAYOUT_HOLD_DAYS`) rather than transferred immediately; matured earnings are paid
   in one aggregated payout on the biweekly run (`scripts/run_biweekly_payouts.py` /
   `POST /admin/payouts/run`), and a report can hold a seller's payouts pending review.
   See `docs/PAYOUT_HOLD_AND_SCHEDULE.md`. So the local E2E now shows
   `compute_tx_status: PAYMENT_CAPTURED` (seller payout held), not an immediate transfer.
   (The `pytorch-matmul-v1` numeric validator in `lumaris_api/matmul_validation.py`
   is still the gate that must be wired before matmul jobs can auto-settle.)

4. **Stripe ≥15 webhook event shape.** The fake gateway verifies webhooks with the
   *real* verifier, and stripe 15.x requires a top-level `object: "event"` field or
   `construct_event` raises. Not an app bug (real Stripe sends it), but a gotcha for
   any internally-constructed event or test tooling.

## Confirmed working (positives)

- Ed25519 result signing + attestation binding (`/prove` → `/jobs/result`).
- Server-generated known-answer validation (`dispatch_test` → correct hash → `test_passed`).
- The `seller-not-payout-ready` gate correctly blocks `/payments/authorize` (409).
- The full FSM `authorize → reserve → dispatch → meter → capture → transfer → COMPLETED`
  with correct amounts (captured = metered) and `reconciled` status.

## Scope / honesty

- This exercises the **notebook** task path for the paid job (the agent runs
  notebook jobs CPU-only today) and the **test** known-answer path. It does **not**
  execute a real GPU workload (no GPU in the sandbox) and does **not** use real
  Stripe — the fake gateway stands in. It proves the *platform wiring* end-to-end;
  real GPU execution + real Stripe still need the Droplets (see
  `docs/BUYER_SELLER_GPU_E2E_REPORT.md`).
