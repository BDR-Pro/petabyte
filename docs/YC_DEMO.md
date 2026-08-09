# Petabyte — YC demo procedure

The canonical Petabyte demonstration runs **entirely in the browser** at
petabyte.market. A non‑technical presenter completes the whole two‑sided
marketplace lifecycle — a seller brings a GPU online, a buyer rents it, runs a
real workload, pays by card, and both sides see the money — **without ever
touching `curl` or an internal `/payments/*` endpoint**. Those APIs still exist
underneath the UI and are covered by automated tests; the demo never calls them
by hand.

There are two ways to run it:

| | Purpose | Stripe | GPU | Command |
|---|---|---|---|---|
| **A. Live demo** | On‑stage / investor call | **real Stripe TEST mode** | **real self‑hosted GPU** | deploy + click through the browser |
| **B. Automated browser E2E** | Repeatable proof in CI | offline fake gateway (test mode) | none (hermetic) | `make browser-e2e` |

Nothing is faked in either path in a way that would mislead: the buyer's
on‑screen “you were charged $X” is always backed by a **real capture** on the
server, seller earnings are computed from that real capture, and the **real GPU
hardware** is proven by a separate, independent CI job (see
[§5](#5-where-the-real-gpu-is-proven)). Stripe stays in **TEST mode** throughout —
no real money moves.

---

## 1. What the demo shows (the lifecycle)

```
SELLER                                   BUYER
  install agent → GPU online + verified
  listing visible in /marketplace
  /seller/payouts → payout‑ready
                                         open petabyte.market → /marketplace
                                         pick a GPU → /buy/<gpu>
                                         write a workload, "Rent & run"
                                         Stripe TEST card checkout
        ── card authorized (a hold, not a charge) ──
                                         GPU reserved
                                         workload dispatched
  agent runs the workload on the real GPU
  agent reports the result
        ── metered → captured (charged for ACTUAL usage) ──
                                         sees workload output + receipt
  /seller/payouts → earnings ↑, payout HELD 14 days
```

The browser shows **friendly progress states** (“Reserving your GPU…”, “Running
on the GPU…”, “Done — charged for actual usage”), never raw state‑machine names.

---

## 2. Live demo — one‑time setup

You need the API deployed (or run locally) in **real Stripe TEST mode**, plus a
machine with an NVIDIA GPU running the Petabyte agent.

### 2a. API in real Stripe TEST mode

Set these (see `template.env` / `docs/` for the full list):

```bash
STRIPE_GATEWAY=real                 # use the real Stripe API (not the offline fake)
STRIPE_MODE=test                    # TEST mode
STRIPE_SECRET_KEY=sk_test_...       # your Stripe TEST secret key
STRIPE_PUBLISHABLE_KEY=pk_test_...  # your Stripe TEST publishable key (used by the browser)
STRIPE_WEBHOOK_SECRET=whsec_...     # from `stripe listen` or the dashboard
CONNECT_RETURN_URL=https://<host>/seller/payouts
CONNECT_REFRESH_URL=https://<host>/seller/payouts
# Do NOT set PAYMENTS_LIVE_ENABLED. A live key without it fails closed by design.
```

The app refuses to start in production with the fake gateway, and refuses a
`sk_live_` key unless payments‑live is explicitly enabled — so a demo cannot
accidentally move real money. Forward webhooks during the demo with:

```bash
stripe listen --forward-to https://<host>/webhooks/stripe
```

### 2b. A seller GPU, online and payout‑ready

1. On the GPU machine, install the agent (the `/install` page has the one‑liner).
   On startup it **attests** the hardware (signs a proof with a key held on the
   machine) and **heartbeats**. The GPU then appears in `/marketplace`, marked
   *verified*.
2. Sign in as the seller → **`/seller/payouts`** → **Connect Stripe account** →
   complete Stripe’s **test‑mode** onboarding (Stripe provides test values). When
   Stripe sends `account.updated`, the page flips to **payout‑ready**, and the
   *Your GPUs* section shows the node as **online · verified · visible to buyers**.

> Payout‑readiness is decided by the backend from a verified, enabled payout
> rail — it is never something the browser can toggle. A non‑payout‑ready seller
> cannot take paid jobs (the buyer’s quote/authorize is refused).

---

## 3. Live demo — the run (all in the browser)

1. **Buyer** opens petabyte.market → **Marketplace** → clicks the seller’s GPU →
   **Rent & run on this GPU →** (this is `/buy/<gpu>`).
2. Set a **max runtime** and edit the **workload code** (the default is a small
   CUDA matmul that prints the GPU name — good for a demo).
3. Click **Rent & run**. The page:
   - shows the **authorization** amount (“authorized up to $X — charged only for
     what you use”);
   - mounts the **Stripe card element**. Enter the test card
     **`4242 4242 4242 4242`**, any future expiry, any CVC, any ZIP, and press
     **Pay**;
   - walks **card authorized → GPU reserved → sending workload → running on the
     GPU** with a live checklist.
4. The seller’s agent claims the job, runs it **on the real GPU**, and reports the
   result. The transaction is **metered and captured** for actual usage.
5. The buyer sees **“Done — you were charged $X”**, the **workload output**, and a
   **receipt**. The unused part of the authorization hold is released
   automatically.
6. **Seller** refreshes **`/seller/payouts`**: gross compute, commission, and net
   earnings go up, and the job appears in the table. The **payout is held for 14
   days** (Petabyte does not pay the seller instantly) — a real risk control, not
   a demo shortcut. There is no “force payout” button.

### Handy Stripe TEST cards

| Card | Behaviour |
|---|---|
| `4242 4242 4242 4242` | succeeds (use this) |
| `4000 0000 0000 9995` | declined (insufficient funds) — shows the buyer a clean error |
| `4000 0025 0000 3155` | requires 3‑D Secure authentication |

---

## 4. Automated browser E2E (the repeatable proof)

`scripts/e2e/browser_e2e.py` drives this **exact journey** through a real Chromium
browser (Playwright) against a local `uvicorn` server with the **offline fake
Stripe gateway** in test mode — hermetic, no secrets, no network, no GPU.

```bash
pip install -r lumaris_api/requirements.txt playwright
python -m playwright install chromium
make browser-e2e            # or: python scripts/e2e/browser_e2e.py
```

It brings a seller GPU online + verified + payout‑ready (using the agent’s real
Ed25519 signing and a genuinely‑signed Stripe webhook), then drives the buyer’s
browser through select → workload → checkout → reserve → dispatch → run →
capture, and asserts, among other things:

- the GPU is **bookable** and the buyer can complete checkout in the browser;
- the UI reaches a **friendly** completed state (no raw FSM name in the headline);
- the buyer sees the **workload output** and a **receipt**;
- **ground truth:** the transaction actually reached `PAYMENT_CAPTURED` on the
  server with a **non‑zero captured amount** — the UI success is not faked;
- the **seller** page shows the GPU as *online · verified · visible to buyers* and
  the **earnings** reflect the real captured sale.

In fake‑gateway mode the browser uses the sandbox card confirmation
(`/payments/{id}/simulate-card`), which returns **404 whenever the real Stripe
gateway is active** — so it can never confirm a real PaymentIntent. In real TEST
mode (the live demo) the browser uses **Stripe.js Elements** with a test card
instead. The page chooses automatically from `GET /payments/config`.

This job runs in CI as **`browser-e2e`** in `.github/workflows/tests.yml`.

The stand‑in node in this hermetic test reports a result string that is
explicitly labelled as an offline test stand‑in — it does **not** claim to be
real GPU output. Real GPU execution is proven separately:

---

## 5. Where the real GPU is proven

The browser E2E deliberately does **not** assert real GPU work — that would
require faking it in CI. Instead, genuine GPU execution is proven by an
independent, opt‑in job on real hardware:

- **`.github/workflows/load_test.yml` → `smoke-gpu`** (`runs-on: [self-hosted,
  gpu]`, triggered via *Run workflow* with `run_gpu=true`).
- It runs **`scripts/smoke_gpu.py`**, which verifies the GPU is visible **inside
  the Petabyte container runtime**, runs a bounded PyTorch matmul, samples
  `nvidia-smi utilization.gpu`, and requires **peak utilisation ≥ threshold** and
  a clean container teardown. Missing hardware is reported as
  `EXTERNAL_GPU_TEST_REQUIRED` — **never a fake PASS** — and is a hard failure
  when a GPU box was explicitly requested (`SMOKE_GPU_REQUIRED=1`).
- **`scripts/e2e_marketplace_test.py`** (`make e2e-real SPEC=<public-id>`) goes
  further: it runs a bounded CUDA workload **inside the real payment lifecycle**
  against a real Stripe TEST key and a real seller GPU, and asserts the captured
  amount equals fee + net. It refuses `sk_live_` keys.

So: the **UI + payment plumbing** is proven hermetically by `browser-e2e`, and
the **GPU is genuine** by `smoke-gpu` / `e2e_marketplace_test.py`. Together they
back every claim the demo makes.

---

## 6. What is never faked

- **Payment success** — the buyer is only shown “charged” after a real
  server‑side capture (verified in the automated test).
- **GPU utilisation / job completion** — proven on real hardware in CI, never
  simulated as real in the demo.
- **Seller earnings / payout readiness** — computed from real captures and a
  verified payout rail; the 14‑day payout hold is real and cannot be shortcut.
- **Stripe mode** — TEST mode only; the app fails closed against live keys unless
  payments‑live is explicitly enabled, and the sandbox card path is inert under
  the real gateway.
