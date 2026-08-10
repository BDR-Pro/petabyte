#!/usr/bin/env python3
"""browser_e2e.py — the YC demo journey, proven through the REAL browser UI.

Drives the ENTIRE Stripe compute-tx marketplace lifecycle from the buyer's browser
(Chromium via Playwright) — NOT by curling /payments/authorize|reserve|dispatch|confirm.
It runs against the real uvicorn API with the offline fake Stripe gateway in test mode,
so it is hermetic: no secrets, no network, no GPU, deterministic in CI.

  seller (its GPU agent, emulated here with the agent's REAL Ed25519 crypto) brings a
    GPU online + verified + payout-ready
  -> buyer opens /buy/<gpu> in the browser, submits a workload, clicks "Rent & run"
  -> the page walks authorize -> card (sandbox confirm) -> reserve -> dispatch -> run
  -> the seller NODE claims the job via the REAL /jobs/next and reports completion via
     the REAL /jobs/result, which auto-captures the buyer
  -> the page shows friendly progress, then the workload output + a receipt
  -> the seller earnings page reflects the captured sale.

What this proves: the UI + payment plumbing end-to-end. What it does NOT do: fake GPU
work. The stand-in node's reported output is explicitly labelled as a test stand-in,
and the "you were charged" the buyer sees is verified against the server actually
capturing the PaymentIntent. The REAL self-hosted GPU hardware assertion is a separate,
independent proof in .github/workflows/load_test.yml (scripts/smoke_gpu.py), which this
test deliberately does not replace.

Run: python scripts/e2e/browser_e2e.py
"""
import base64
import os
import sys
import threading
import time

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import local_e2e as le  # noqa: E402  (reuse the faithful server bootstrap + agent crypto)

B = le.BASE
PW = "pw-correct-horse-1"

# The stand-in node's reported output. It is HONEST about what it is: this hermetic
# test does not run a GPU; real GPU execution is proven separately (see module docstring).
NODE_RESULT = (
    "cuda available: True\n"
    "[offline browser-e2e node] workload received and completed.\n"
    "Real GPU execution is asserted independently by scripts/smoke_gpu.py in CI."
)

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        _fail += 1


def bearer(t):
    return {"Authorization": "Bearer " + t}


def _seed(c):
    """Bring a seller GPU online+verified+payout-ready and register a buyer — using the
    same real endpoints the production agent and Stripe webhooks use."""
    for u in ("admin1", "seller1", "buyer1"):
        c.post(f"{B}/register_user", json={"username": u, "password": PW})
    seller_t = le.token_for(c, "seller1", PW)
    buyer_t = le.token_for(c, "buyer1", PW)
    c.post(f"{B}/change_role", headers=bearer(seller_t), json={"role": "seller"})

    kr = c.post(f"{B}/create_api_key?days=90&scopes=node,jobs", headers=bearer(seller_t))
    sk = {"X-API-KEY": kr.json()["api_key"]}

    sr = c.post(f"{B}/register_specs", headers=bearer(seller_t),
                json={"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 1.5,
                      "provider": "local", "gpu_model": "NVIDIA L4", "gpu_count": 1,
                      "vram_gb": 24, "units": 1, "region": "us-east", "country": "US"})
    spec_id = sr.json()["spec_id"]

    att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(),
           "ts": int(time.time())}
    c.post(f"{B}/prove", headers=bearer(seller_t),
           json={"spec_id": spec_id, "attestation": att,
                 "signature": le.agent_crypto.sign_proof(att),
                 "pubkey": le.agent_crypto.public_key_b64()})
    c.post(f"{B}/heartbeat", headers=sk, json={"spec_id": spec_id})

    ca = c.post(f"{B}/payments/connect/account", headers=bearer(seller_t),
                json={"country": "US", "email": "seller1@example.com"})
    acct = ca.json()["connected_account_id"]
    le.post_stripe_webhook(c, {
        "id": "evt_acct_1", "type": "account.updated",
        "data": {"object": {"id": acct, "charges_enabled": True, "payouts_enabled": True,
                            "details_submitted": True,
                            "capabilities": {"transfers": "active", "card_payments": "active"},
                            "requirements": {"currently_due": [], "past_due": []}}}})
    st = c.get(f"{B}/payments/connect/status", headers=bearer(seller_t)).json()
    ok("seller is payout-ready after signed onboarding webhook", bool(st.get("payout_ready")))

    specs = c.get(f"{B}/marketplace/specs").json()
    specs = specs if isinstance(specs, list) else specs.get("specs", [])
    mine = [s for s in specs if s.get("gpu_model") == "NVIDIA L4"]
    ok("seller GPU is visible in the marketplace (online + verified)", bool(mine))
    pub = mine[0]["id"] if mine else None
    if pub:
        detail = c.get(f"{B}/marketplace/specs/{pub}").json()
        ok("GPU is bookable (online, has capacity, can accept paid jobs)",
           detail.get("online") and detail.get("available_units", 0) > 0
           and detail.get("can_accept_paid_jobs"))
    return seller_t, buyer_t, sk, pub


def _node_loop(sk, stop):
    """Emulate the seller's GPU agent: claim jobs and report completion through the REAL
    node endpoints. In the live demo this is a real machine running the workload."""
    with httpx.Client(timeout=10) as nc:
        while not stop.is_set():
            try:
                r = nc.get(f"{B}/jobs/next", headers=sk)
                if r.status_code == 200 and r.json():
                    j = r.json()
                    tid = j.get("task_id")
                    if tid and j.get("task_type") == "test":
                        h = le.agent_crypto.compute_test_hash(int(j["size"]), int(j["seed"]))
                        nc.post(f"{B}/jobs/result", headers=sk,
                                json={"task_id": tid, "status": "completed", **le.signed_proof(h)})
                    elif tid:
                        nc.post(f"{B}/jobs/result", headers=sk,
                                json={"task_id": tid, "status": "completed", "result": NODE_RESULT,
                                      **le.signed_proof("sha256:" + "0" * 64)})
            except Exception:
                pass
            stop.wait(0.4)


def _launch(p):
    try:
        return p.chromium.launch(args=["--no-sandbox"])
    except Exception:
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE",
                             "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        return p.chromium.launch(executable_path=exe, args=["--no-sandbox"])


def _run_browser(c, buyer_t, seller_t, pub):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = _launch(p)
        try:
            page = browser.new_page()
            # Authenticate the browser exactly like the app does: JWT in localStorage.
            page.goto(B + "/")
            page.evaluate("t => localStorage.setItem('pb_token', t)", buyer_t)

            page.goto(B + "/buy/" + pub)
            page.wait_for_selector("#buy_pay", timeout=20000)
            ok("buy page renders the GPU and a Rent & run button", "NVIDIA L4" in page.content())
            ok("Rent & run button is enabled (GPU bookable in the UI)",
               not page.is_disabled("#buy_pay"))

            page.click("#buy_pay")
            # The whole lifecycle runs behind the button; wait for the terminal result card.
            page.wait_for_selector("#buy_result", state="visible", timeout=120000)
            msg = (page.text_content("#buy_msg") or "")
            body = (page.text_content("#buy_result_body") or "")

            ok("UI reaches a friendly completed state (not a raw FSM name)",
               "Done" in msg and "charged" in msg.lower())
            ok("no internal state-machine name is shown as the headline",
               not any(s in msg for s in ("PAYMENT_CAPTURED", "GPU_RESERVED",
                                          "METERING_FINALIZED", "PAYMENT_CAPTURE_PENDING")))
            ok("buyer sees the workload output", "browser-e2e node" in body)
            ok("buyer sees a receipt", "Receipt" in body)

            # Ground truth: the "you were charged" the UI shows is backed by a REAL capture.
            tx_id = page.evaluate("() => window.TX")
            ok("browser drove a real transaction", bool(tx_id))
            pv = c.get(f"{B}/payments/{tx_id}", headers=bearer(buyer_t)).json()
            ok("server actually CAPTURED the payment (UI success is not faked)",
               pv.get("status") in ("PAYMENT_CAPTURED", "SELLER_TRANSFER_PENDING",
                                     "SELLER_TRANSFERRED", "COMPLETED"))
            ok("buyer was charged a real, non-zero amount",
               (pv.get("captured_amount") or 0) > 0)

            # Seller side of the journey: earnings/payout state, in the browser.
            page.goto(B + "/")
            page.evaluate("t => localStorage.setItem('pb_token', t)", seller_t)
            page.goto(B + "/seller/payouts")
            page.wait_for_selector("#earn_rows", timeout=20000)
            page.wait_for_function(
                "() => { var e=document.getElementById('earn_rows');"
                " return e && e.textContent.indexOf('loading')<0; }", timeout=20000)
            nodes_txt = (page.text_content("#nodes_box") or "")
            rows_txt = (page.text_content("#earn_rows") or "")
            ok("seller page shows the GPU as online + verified + visible to buyers",
               "online" in nodes_txt and "verified" in nodes_txt and "visible to buyers" in nodes_txt)
            ok("seller earnings table shows the paid job in the browser", "ctx_" in rows_txt)

            # Ground truth for the seller money.
            earn = c.get(f"{B}/seller/earnings/stripe", headers=bearer(seller_t)).json()
            ok("seller gross compute earnings are real and non-zero",
               (earn.get("gross_compute_minor") or 0) > 0)
            ok("seller has at least one captured job", len(earn.get("jobs") or []) >= 1)
        finally:
            browser.close()


def main():
    proc, log, _db = le.start_server()
    stop = threading.Event()
    node_t = None
    try:
        if not le.wait_up():
            print("SERVER FAILED TO START — last log lines:")
            try:
                print(open(log.name).read()[-3000:])
            except Exception:
                pass
            return 2
        with httpx.Client(timeout=30) as c:
            seller_t, buyer_t, sk, pub = _seed(c)
            if not pub:
                print("no bookable spec — cannot run the browser journey")
                return 1
            node_t = threading.Thread(target=_node_loop, args=(sk, stop), daemon=True)
            node_t.start()
            _run_browser(c, buyer_t, seller_t, pub)
    finally:
        stop.set()
        if node_t:
            node_t.join(timeout=3)
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            log.close()
        except Exception:
            pass

    print(f"\n=== browser_e2e: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
