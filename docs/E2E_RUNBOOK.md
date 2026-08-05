# Live buyer→seller E2E runbook (Option A: run it from the Droplets)

You chose **Option A**: you drive the flow from the Droplets (which have real
network access), and I provide exact commands + scripts. This file is that
playbook. Two helper scripts back it:

- `scripts/e2e/seller_setup.sh` — run on the **seller** Droplet (165.22.236.63).
- `scripts/e2e/buyer_probe.py` — run on the **buyer** Droplet (137.184.198.133).

> **Read this first — scope honesty.** The payment state machine
> (authorize→reserve→dispatch→meter→capture→transfer) is real and tested. But
> the *validated GPU-matmul* job the task asks for is **not built yet** and the
> paid path is **not fully wired** (see `docs/BUYER_SELLER_GPU_E2E_REPORT.md`
> §4). So this runbook proves the pipeline **as far as it currently goes**:
> - `notebook` jobs run **CPU-only** in the current agent (no `--gpus`).
> - Real GPU execution today exists only for `render`/`transcode` (need media
>   inputs) — and as a synthetic known-answer `test` (CPU).
> - `pytorch-matmul-v1` and its numeric validation must be implemented before a
>   true "buyer pays → GPU matmul → validated → captured → seller paid" run can
>   pass. The validator core is already written + unit-tested
>   (`lumaris_api/matmul_validation.py`); the workload, agent harness, metering
>   bridge, and paid-path wiring are the remaining build.

Never put passwords, SSH keys, or Stripe keys in chat, logs, git, or shell
history. Use TEST Stripe keys only (`sk_test_`/`pk_test_`).

---

## Phase 0 — Platform preconditions (verify once)

On the deployed platform (`petabyte.market`), confirm Stripe is in **test mode**:

```
STRIPE_MODE=test
PAYMENTS_LIVE_ENABLED=false
STRIPE_GATEWAY=real          # real SDK, test keys (fake gateway won't create real test objects)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...   # from `stripe listen` or the dashboard
```

Point Stripe test webhooks at `https://petabyte.market/webhooks/stripe`
(and the legacy `/webhooks/payment` if used). Quick liveness:

```
curl -s https://petabyte.market/healthz            # or the site root
curl -s https://petabyte.market/marketplace/specs  # public inventory (no auth)
```

Also: log in on the site as **testUserSeller** and complete **Stripe Connect
test onboarding** (Payments/Connect in the seller dashboard). Until that's done,
`seller_payout_ready` is false and transfers can't settle — `buyer_probe.py`
prints that flag from the quote.

## Phase 1 — Seller GPU Droplet (165.22.236.63)

SSH in as root, clone/pull the repo (for the script), then:

```bash
PETABYTE_API_URL=https://petabyte.market \
SELLER_USER=testUserSeller \
PRICE_PER_HOUR=1.5 \
bash scripts/e2e/seller_setup.sh
```

It mints a node key for the seller account (prompts for the password with hidden
input), runs the official installer (`install.sh`: detects the GPU via
`nvidia-smi`, attests with a fresh Ed25519 key, registers the spec, starts the
`petabyte-agent` systemd service), and verifies GPU + Docker-GPU + agent health.

**Success looks like:** `systemctl status petabyte-agent` = active; the Docker-GPU
smoke prints `nvidia-smi` from inside a container; and the node appears in
`GET /marketplace/specs` as attested with `available_units >= 1`.

## Phase 2 — Buyer Droplet (137.184.198.133)

SSH in, `pip install httpx stripe`, then drive the flow. Fully headless (auto-confirms
the card with a Stripe TEST secret you control):

```bash
BUYER_USER=testUser \
STRIPE_TEST_SECRET_KEY=sk_test_... \
python3 scripts/e2e/buyer_probe.py --seconds 60 --task-type notebook
```

Or two-phase with a **browser** card confirm (test card `4242 4242 4242 4242`,
any future expiry / CVC / postal):

```bash
BUYER_USER=testUser python3 scripts/e2e/buyer_probe.py --seconds 60   # stops after authorize
# ...confirm the card in the browser checkout...
python3 scripts/e2e/buyer_probe.py --resume <transaction_id>          # reserve → dispatch → poll
```

The script walks: login → list specs → **quote** → **authorize** (manual-capture
PaymentIntent) → **confirm** → **reserve** (requires `PAYMENT_AUTHORIZED`) →
**dispatch** → poll `/payments/{id}` + `/tasks/{id}` → **receipt**, and prints a
correlation summary (transaction id, task id, amounts, statuses).

For the **required browser proof**, also run the buyer journey through the website
with Playwright from this Droplet (Chromium is preinstalled in this repo's
environments; on the Droplet, `pip install playwright && playwright install
chromium`). Record a trace of: login → GPU selection → template → quote → Stripe
test checkout → job progress → validation → result → receipt.

## Phase 3 — Settlement (capture + seller transfer)

Capture and transfer are admin/orchestrator-gated in this build. As an admin
(add the account to `ADMIN_USERS`), after the job completes and metering is set:

```bash
TX=<transaction_id>; TOKEN=<admin bearer>
curl -s -X POST "https://petabyte.market/admin/payments/$TX/meter"    -H "Authorization: Bearer $TOKEN" -d '{"actual_seconds":57}'
curl -s -X POST "https://petabyte.market/admin/payments/$TX/capture"  -H "Authorization: Bearer $TOKEN"
curl -s -X POST "https://petabyte.market/admin/payments/$TX/transfer" -H "Authorization: Bearer $TOKEN"
```

Then reconcile and confirm records match:

```bash
curl -s "https://petabyte.market/payments/$TX/receipt" -H "Authorization: Bearer $TOKEN"
curl -s "https://petabyte.market/admin/webhooks"       -H "Authorization: Bearer $TOKEN"
# repo-side reconcile (buyer/seller/platform/ledger): python lumaris_api/reconcile.py
```

**Success:** `captured_amount` = metered amount, `platform_fee` + `seller_net`
add up, `stripe_transfer_id` set, and the ledger balances.

## What still needs building for the FULL task (before a matmul paid run passes)

From `docs/BUYER_SELLER_GPU_E2E_REPORT.md` §4 — none are external blockers:

1. **`pytorch-matmul-v1` workload + agent harness** — a versioned GPU container
   that runs the seeded matmul and emits the result manifest (the benchmark
   harness is currently a stub).
2. **Agent→metering bridge** — feed real GPU wall-clock into `record_metering`
   (today metering seconds come from the admin endpoint).
3. **Wire `matmul_validation.py` into `/jobs/result`** — enforce
   VALID-before-pay (the validator + 21 tests already exist).
4. **Route the paid buyer path through the ComputeTransaction FSM** — the repo's
   own "central rewire" (`docs/REMOVED_PAYMENT_STUBS.md:91`).

Only after 1–4 can you mark `artifacts/e2e-run-state.json` `SUCCEEDED` — and only
with real evidence for every completion criterion (two consecutive standard
runs, validation states, ledger balanced, no duplicate capture/transfer).
