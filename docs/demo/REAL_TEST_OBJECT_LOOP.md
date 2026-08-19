# Real-Stripe-test-object end-to-end demo loop

The complete, repeatable **buyer → GPU → payout → proof** loop with **no simulated payments**.
Everything moves through the same code paths production uses; only the Stripe *keys* are test
keys (`sk_test_…`), so the money objects are genuine Stripe test objects, not fakes.

```
buyer authorize (real Stripe TEST PaymentIntent, manual capture)
   → confirm (server re-verifies Stripe)  → reserve → dispatch ONCE
   → seller agent runs the workload → signs the result (Ed25519)
   → auto meter + capture (partial, on real usage)
   → provider payout (Stripe TEST transfer to the seller's connected account)
   → unified PROOF (payment + signed compute receipt + payout) in one artifact
```

## One command

```bash
# 1. Point the SERVER at real Stripe TEST + real gateway (never live — the gateway hard-refuses
#    live keys unless three explicit prod flags are all set):
export STRIPE_GATEWAY=real STRIPE_SECRET_KEY=sk_test_… STRIPE_PUBLISHABLE_KEY=pk_test_…
export PAYOUT_HOLD_DAYS=0            # pay in-session for the demo (default 14-day risk hold)
export ADMIN_USERS=you@example.com   # an admin drives the payout leg

# 2. Make the seller payout-ready headlessly (no hosted-onboarding click-through):
python - <<'PY'
import db, stripe_connect as sc
s = db.SessionLocal(); u = db.get_user_by_username(s, "your_seller")
ca = sc.ensure_test_payout_ready(s, u, country="US")   # TEST-mode only; fails closed on live
print("payout_ready:", ca.payout_ready())
PY

# 3. Drive the whole loop, including the payout leg, against the running API:
export E2E_ADMIN_USERNAME=you@example.com E2E_ADMIN_PASSWORD=…
python scripts/e2e_marketplace_test.py --api https://petabyte.market \
       --spec <public-spec-id> --settle-payout
```

Without `--settle-payout` (or without admin creds) the run stops at capture and the seller net
is **HELD by design** for the payout hold — the historical "PENDING BY DESIGN" behavior, still
available. With it, the runner drives `POST /admin/payments/{tx}/transfer` (a real Stripe TEST
transfer) and re-reads the proof to confirm the payout settled.

## The proof artifact

`GET /payments/{tx}/proof` (buyer / seller / admin scoped) returns **one** object that proves
the entire loop:

- **payment** — PaymentIntent id, authorized max, captured, refunded, metered seconds;
- **compute** — the cryptographic per-job receipt: Ed25519 signature over the signed payload,
  sha256 of the real output bytes, the node's attested pubkey, and a **live** server
  re-verification (`server_reverified: true`) — re-checkable offline;
- **payout** — seller net, obligation state, `stripe_transfer_id`, and `hold_status`
  (`held` → `released`).

Nothing in it is simulated when the server runs the real gateway.

## Safety rails (unchanged, no override)

- The runner refuses any key that is not `sk_test_…` and aborts if a created PaymentIntent has
  `livemode != false`. There is no `--force`.
- `ensure_test_payout_ready` calls `assert_test_mode()` and **fails closed** in live mode.
- Secrets (keys, `client_secret`, JWT, webhook secret) are never printed or written to
  artifacts (redacted by `scrub()`).

## Hermetic coverage (runs in CI, no Stripe account needed)

`lumaris_api/demo_payout_loop_test.py` exercises this exact loop with the offline
`FakeStripeGateway` and the real Ed25519 signer: headless onboarding → capture → **payout
transfer** → the unified proof shows a real transfer id + a `paid` obligation, idempotent and
access-controlled. `stripe_e2e_flow_test.py` covers the complementary held-payout (14-day hold)
path. Both are green in `make test` and CI.

## What is still a real prerequisite (not simulated away)

For a *GPU-validated* paid run specifically, the `pytorch-matmul-v1` validated workload +
`matmul_validation.py` wiring remain the honest gap (see `docs/E2E_RUNBOOK.md` §"What still
needs building"); the notebook path runs CPU-sandboxed, while `render`/`transcode` use real
`--gpus`. The payment + payout + proof loop above is complete and real for all job types today.
