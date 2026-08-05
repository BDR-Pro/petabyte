#!/usr/bin/env python3
"""buyer_probe.py — drive the live Petabyte buyer payment→dispatch pipeline.

Run this ON the buyer Droplet (137.184.198.133), which can reach the public site.
It uses ONLY the public API (the same endpoints the website calls), logs in as the
buyer, finds the seller's GPU, and walks the Stripe-native flow:

    login → list specs → quote → authorize → confirm → reserve → dispatch
          → poll payment + task → receipt

and prints one correlation summary (transaction id, task id, amounts, statuses).

CARD CONFIRMATION. `authorize` creates a manual-capture PaymentIntent and returns
its client_secret. Someone must confirm that PI with a Stripe TEST card before the
GPU can be reserved. Two ways:
  * Browser: open the checkout page, pay with 4242 4242 4242 4242 (any future
    expiry / CVC / postal), then re-run with `--resume <transaction_id>`.
  * Headless: pass `--stripe-test-secret sk_test_...` (the platform's TEST secret,
    which the operator controls) and this script confirms the PI with
    `pm_card_visa` for you. NEVER use a live key; NEVER commit the key.

Capture + seller transfer are admin/orchestrator-gated in this build
(/admin/payments/{id}/{meter,capture,transfer}); this script stops at a captured
receipt if you drive those, and otherwise reports the transaction up to dispatch.

Secrets: the buyer password is read with getpass (never echoed / never in argv).

Examples:
  BUYER_USER=testUser python3 scripts/e2e/buyer_probe.py --gpu "" --seconds 60 \
      --stripe-test-secret "$STRIPE_TEST_SECRET_KEY"
  python3 scripts/e2e/buyer_probe.py --resume ctx_abc123
"""
import argparse
import getpass
import os
import sys
import time

import httpx

API = os.environ.get("PETABYTE_API_URL", "https://petabyte.market").rstrip("/")
TIMEOUT = 30.0


def die(msg, resp=None):
    print(f"FAIL: {msg}")
    if resp is not None:
        print(f"  HTTP {resp.status_code}: {resp.text[:400]}")
    sys.exit(1)


def login(client) -> str:
    user = os.environ.get("BUYER_USER") or input("Buyer username: ").strip()
    pw = os.environ.get("BUYER_PASS") or getpass.getpass("Buyer password (hidden): ")
    r = client.post(f"{API}/login", data={"username": user, "password": pw})
    if r.status_code != 200:
        die("login failed", r)
    print(f"ok  logged in as {user}")
    return r.json()["access_token"]


def pick_spec(client, gpu_filter, spec_id):
    r = client.get(f"{API}/marketplace/specs")
    if r.status_code != 200:
        die("could not list marketplace specs", r)
    specs = r.json()
    specs = specs if isinstance(specs, list) else specs.get("specs", [])
    live = [s for s in specs if s.get("available_units", 0) >= 1]
    print(f"ok  marketplace lists {len(live)} bookable GPU(s)")
    if spec_id:
        for s in live:
            if s["id"] == spec_id:
                return s
        die(f"spec_id {spec_id} not found among bookable specs")
    if gpu_filter:
        live = [s for s in live if gpu_filter.lower() in (s.get("gpu_model") or "").lower()]
    if not live:
        die("no matching bookable seller GPU is visible — is the seller agent "
            "attested, online, and can_accept_paid_jobs?")
    s = live[0]
    print(f"    -> using spec {s['id']}: {s.get('gpu_model')} "
          f"{s.get('vram_gb')}GB @ {s.get('price_per_hour')}/h (units {s.get('available_units')})")
    return s


def confirm_pi_headless(client_secret, secret_key):
    try:
        import stripe
    except ImportError:
        die("the 'stripe' package is not installed; pip install stripe or use --resume")
    if not secret_key.startswith("sk_test_"):
        die("refusing to use a non-test Stripe key (must start with sk_test_)")
    stripe.api_key = secret_key
    pi_id = client_secret.split("_secret_")[0]
    pi = stripe.PaymentIntent.confirm(pi_id, payment_method="pm_card_visa")
    print(f"ok  confirmed PaymentIntent {pi_id} with test card -> {pi.status}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", default=None, help="substring filter on gpu_model")
    ap.add_argument("--spec-id", default=None)
    ap.add_argument("--seconds", type=int, default=60, help="estimated runtime")
    ap.add_argument("--task-type", default="notebook",
                    help="notebook|test|benchmark|render|transcode|template "
                         "(NOTE: notebook runs CPU-only in the current agent)")
    ap.add_argument("--code", default="import torch;print('cuda',torch.cuda.is_available())")
    ap.add_argument("--stripe-test-secret", default=os.environ.get("STRIPE_TEST_SECRET_KEY"))
    ap.add_argument("--resume", default=None, help="transaction_id to resume after a browser card confirm")
    args = ap.parse_args()

    with httpx.Client(timeout=TIMEOUT) as client:
        token = login(client)
        client.headers["Authorization"] = f"Bearer {token}"

        if args.resume:
            tx_id = args.resume
            print(f"ok  resuming transaction {tx_id}")
        else:
            spec = pick_spec(client, args.gpu, args.spec_id)
            q = client.post(f"{API}/payments/quote",
                            json={"spec_id": spec["id"], "estimated_seconds": args.seconds})
            if q.status_code != 200:
                die("quote failed", q)
            qj = q.json()
            print(f"ok  quote: auth_max={qj['authorization_amount']} {qj['currency']} "
                  f"(est compute {qj['estimated_compute_amount']}), "
                  f"seller_payout_ready={qj.get('seller_payout_ready')}")

            a = client.post(f"{API}/payments/authorize",
                            json={"spec_id": spec["id"], "estimated_seconds": args.seconds})
            if a.status_code != 200:
                die("authorize failed", a)
            aj = a.json()
            tx_id = aj["transaction_id"]
            cs = aj.get("client_secret")
            print(f"ok  authorized: tx={tx_id} status={aj['status']} "
                  f"auth={aj['authorization_amount']} {aj['currency']}")

            if args.stripe_test_secret and cs:
                confirm_pi_headless(cs, args.stripe_test_secret)
            elif cs:
                print("\nACTION NEEDED: confirm the card in the browser with test card "
                      "4242 4242 4242 4242, then re-run with:")
                print(f"    python3 scripts/e2e/buyer_probe.py --resume {tx_id}")
                print(f"  (client_secret starts with {cs.split('_secret_')[0]}_secret_…)")
                return

        # server-side reconcile of the authorization (verifies with Stripe)
        c = client.post(f"{API}/payments/{tx_id}/confirm")
        if c.status_code != 200:
            die("confirm (mark_authorized) failed — was the card confirmed?", c)
        print(f"ok  authorization reconciled: status={c.json().get('status')}")

        r = client.post(f"{API}/payments/{tx_id}/reserve")
        if r.status_code != 200:
            die("reserve failed (needs PAYMENT_AUTHORIZED + a free unit)", r)
        print(f"ok  GPU reserved: status={r.json().get('status')}")

        d = client.post(f"{API}/payments/{tx_id}/dispatch",
                        json={"task_type": args.task_type, "code": args.code})
        if d.status_code != 200:
            die("dispatch failed", d)
        dj = d.json()
        task_id = dj.get("task_id") or dj.get("task", {}).get("id")
        print(f"ok  dispatched: status={dj.get('status')} task_id={task_id}")
        if args.task_type == "notebook":
            print("    NOTE: the current agent runs notebook jobs CPU-only (no --gpus). "
                  "For real GPU execution use render/transcode, or build pytorch-matmul-v1.")

        # poll the task + transaction
        for _ in range(60):
            pv = client.get(f"{API}/payments/{tx_id}").json()
            tv = client.get(f"{API}/tasks/{task_id}").json() if task_id else {}
            print(f"    poll: tx={pv.get('status')} task={tv.get('status')} "
                  f"progress={tv.get('progress')}")
            if tv.get("status") in ("completed", "failed") or \
               pv.get("status") in ("COMPLETED", "PAYMENT_CAPTURED", "SELLER_TRANSFERRED"):
                break
            time.sleep(5)

        rec = client.get(f"{API}/payments/{tx_id}/receipt")
        print("\n=== correlation summary ===")
        print(f"  transaction_id : {tx_id}")
        print(f"  task_id        : {task_id}")
        if rec.status_code == 200:
            print(f"  receipt        : {rec.json()}")
        print("\nCapture + seller transfer are admin/orchestrator-gated in this build:")
        print(f"  POST {API}/admin/payments/{tx_id}/meter    (finalize metered seconds)")
        print(f"  POST {API}/admin/payments/{tx_id}/capture  (charge actual amount)")
        print(f"  POST {API}/admin/payments/{tx_id}/transfer (pay the seller)")


if __name__ == "__main__":
    main()
