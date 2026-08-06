#!/usr/bin/env python3
"""local_e2e.py — run the Petabyte platform locally and drive a real buyer→seller
flow through it, tracing bugs.

Everything runs INSIDE the sandbox (no Droplets, no real Stripe, no GPU):
  * the real API as a uvicorn server on 127.0.0.1 (SQLite + FakeGateway),
  * a SELLER actor that attests a spec and signs job results with the agent's
    real Ed25519 crypto (lumaris_agent/crypto.py),
  * a BUYER actor that walks the Stripe-native payment + dispatch flow,
  * an ADMIN actor that finalises metering, capture, and the seller transfer.

It prints a step-by-step TRACE and a BUGS list (anything that behaved
unexpectedly). Exit code is non-zero if any BUG was recorded.

Run:  python3 scripts/e2e/local_e2e.py
"""
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import tempfile

import httpx
from cryptography.fernet import Fernet

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API_DIR = os.path.join(REPO, "lumaris_api")
AGENT_DIR = os.path.join(REPO, "lumaris_agent")
HOST, PORT = "127.0.0.1", 8099
BASE = f"http://{HOST}:{PORT}"

TRACE, BUGS = [], []


def trace(msg):
    print("  " + msg)
    TRACE.append(msg)


def bug(msg):
    print("  !! BUG: " + msg)
    BUGS.append(msg)


def expect(label, resp, codes=(200,)):
    """Record a step; flag a BUG if the status isn't expected."""
    okc = resp.status_code in codes
    body = ""
    try:
        body = json.dumps(resp.json())[:200]
    except Exception:
        body = (resp.text or "")[:200]
    trace(f"{label}: HTTP {resp.status_code} {body}")
    if not okc:
        bug(f"{label} expected {codes}, got {resp.status_code}: {body}")
    return resp


# ---- agent signing identity (faithful to the real seller node) ----------------
_agent_key_dir = tempfile.mkdtemp(prefix="pb-agent-")
os.environ["PETABYTE_AGENT_KEY"] = os.path.join(_agent_key_dir, "agent_ed25519.key")
sys.path.insert(0, AGENT_DIR)
import crypto as agent_crypto  # noqa: E402  (lumaris_agent/crypto.py)


def signed_proof(output_hash: str) -> dict:
    proof = {"output_hash": output_hash, "ts": int(time.time())}
    return {"proof": proof, "signature": agent_crypto.sign_proof(proof)}


_WEBHOOK_SECRET = "whsec_local"


def post_stripe_webhook(client, event: dict):
    """Send a genuinely-signed Stripe webhook (the fake gateway uses the REAL
    signature verifier). This is the faithful stand-in for Stripe telling us the
    seller finished onboarding / the PI reached a state."""
    event.setdefault("object", "event")   # stripe>=15 requires a top-level object type
    payload = json.dumps(event, separators=(",", ":")).encode()
    ts = int(time.time())
    sig = hmac.new(_WEBHOOK_SECRET.encode(), f"{ts}.".encode() + payload,
                   hashlib.sha256).hexdigest()
    return client.post(f"{BASE}/webhooks/stripe", content=payload,
                       headers={"Stripe-Signature": f"t={ts},v1={sig}",
                                "Content-Type": "application/json"})


def start_server():
    db_path = os.path.join(tempfile.mkdtemp(prefix="pb-db-"), "local_e2e.db")
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SECRET_KEY": "local-e2e-secret",
        "SERVER_PRIVATE_KEY": Fernet.generate_key().decode(),
        "WG_PUBLIC_KEY": "SERVERPUBLICKEYbase64example==",
        "WG_ENDPOINT": "vpn.local.example",
        "TRUSTED_PROXIES": "127.0.0.1,::1",
        "REAPER_DISABLED": "true",
        "HEARTBEAT_TIMEOUT_S": "120",
        "NOTIFY_STUB": "true",
        "PAYOUT_STUB": "true",
        "S3_STUB": "true",
        "GEOIP_STUB": "true",
        "GOOGLE_OAUTH_STUB": "true",
        "PAYMENT_WEBHOOK_SECRET": "whsec_local",
        "ADMIN_USERS": "admin1",
        "MIN_REPUTATION": "0",
        # Stripe: offline fake gateway, test-mode declared. No real Stripe calls.
        "STRIPE_GATEWAY": "fake",
        "STRIPE_MODE": "test",
        "PAYMENTS_MODE": "sandbox",
        "STRIPE_SECRET_KEY": "sk_test_local",
        "STRIPE_PUBLISHABLE_KEY": "pk_test_local",
        "STRIPE_WEBHOOK_SECRET": "whsec_local",
    })
    log = open(os.path.join(_agent_key_dir, "server.log"), "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", HOST, "--port", str(PORT)],
        cwd=API_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
    return proc, log, db_path


def wait_up(timeout=40):
    for _ in range(timeout * 2):
        try:
            r = httpx.get(f"{BASE}/marketplace/specs", timeout=3)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def token_for(client, username, password):
    r = client.post(f"{BASE}/login", data={"username": username, "password": password})
    return r.json().get("access_token") if r.status_code == 200 else None


def main():
    proc, log, db_path = start_server()
    try:
        print("== starting local Petabyte API ==")
        if not wait_up():
            print("SERVER FAILED TO START — last log lines:")
            print(open(log.name).read()[-3000:])
            return 2
        print(f"server up at {BASE}\n")

        with httpx.Client(timeout=20) as c:
            # -------- bootstrap accounts --------
            print("== bootstrap accounts ==")
            for u in ("admin1", "seller1", "buyer1"):
                expect(f"register {u}", c.post(f"{BASE}/register_user",
                       json={"username": u, "password": "pw-correct-horse-1"}), (200, 400))
            admin_t = token_for(c, "admin1", "pw-correct-horse-1")
            seller_t = token_for(c, "seller1", "pw-correct-horse-1")
            buyer_t = token_for(c, "buyer1", "pw-correct-horse-1")
            for name, t in (("admin", admin_t), ("seller", seller_t), ("buyer", buyer_t)):
                if not t:
                    bug(f"{name} login failed")
            expect("seller -> role seller", c.post(f"{BASE}/change_role",
                   headers={"Authorization": f"Bearer {seller_t}"}, json={"role": "seller"}))

            # -------- SELLER: api key, spec, attest, heartbeat --------
            print("\n== seller onboards a GPU node ==")
            kr = expect("seller mint node key", c.post(
                f"{BASE}/create_api_key?days=90&scopes=node,jobs",
                headers={"Authorization": f"Bearer {seller_t}"}))
            api_key = kr.json().get("api_key")
            SK = {"X-API-KEY": api_key}

            sr = expect("seller register spec", c.post(f"{BASE}/register_specs",
                headers={"Authorization": f"Bearer {seller_t}"},
                json={"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 1.5,
                      "provider": "local", "gpu_model": "NVIDIA L4", "gpu_count": 1,
                      "vram_gb": 24, "units": 1, "region": "us-east", "country": "US"}))
            spec_id = sr.json().get("spec_id")

            att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(),
                   "ts": int(time.time())}
            expect("seller attest (/prove)", c.post(f"{BASE}/prove",
                headers={"Authorization": f"Bearer {seller_t}"},
                json={"spec_id": spec_id, "attestation": att,
                      "signature": agent_crypto.sign_proof(att),
                      "pubkey": agent_crypto.public_key_b64()}))
            expect("seller heartbeat", c.post(f"{BASE}/heartbeat",
                   headers=SK, json={"spec_id": spec_id}))

            # -------- known-answer test workload (validated compute round-trip) -----
            print("\n== validated known-answer test job (seller signs the real answer) ==")
            dt = expect("seller dispatch_test", c.post(f"{BASE}/dispatch_test",
                headers={"Authorization": f"Bearer {seller_t}"},
                json={"spec_id": spec_id, "difficulty": "easy"}), (200, 422))
            # claim it as the node and answer correctly
            claim = expect("seller /jobs/next (test)", c.get(f"{BASE}/jobs/next", headers=SK), (200, 204))
            if claim.status_code == 200 and claim.json().get("task_type") == "test":
                j = claim.json()
                h = agent_crypto.compute_test_hash(int(j["size"]), int(j["seed"]))
                res = expect("seller submit test result", c.post(f"{BASE}/jobs/result",
                    headers=SK, json={"task_id": j["task_id"], "status": "completed",
                                      **signed_proof(h)}))
                if not res.json().get("test_passed"):
                    bug("known-answer test did NOT pass despite correct hash")
            else:
                bug("no 'test' task was handed to the node after dispatch_test")

            # -------- SELLER: Stripe Connect onboarding (fake gateway) --------
            print("\n== seller completes Stripe Connect onboarding ==")
            ca = expect("seller create connected account", c.post(
                f"{BASE}/payments/connect/account",
                headers={"Authorization": f"Bearer {seller_t}"},
                json={"country": "US", "email": "seller1@example.com"}))
            acct_id = ca.json().get("connected_account_id")
            # Stripe would send account.updated once the seller finishes onboarding.
            expect("account.updated webhook accepted", post_stripe_webhook(c, {
                "id": "evt_acct_1", "type": "account.updated",
                "data": {"object": {
                    "id": acct_id, "charges_enabled": True, "payouts_enabled": True,
                    "details_submitted": True,
                    "capabilities": {"transfers": "active", "card_payments": "active"},
                    "requirements": {"currently_due": [], "past_due": []}}}}))
            st = expect("seller connect status", c.get(f"{BASE}/payments/connect/status",
                        headers={"Authorization": f"Bearer {seller_t}"}))
            if not st.json().get("payout_ready"):
                bug("seller still NOT payout-ready after a signed account.updated webhook")

            # -------- BUYER: marketplace + payment FSM (fake gateway) --------
            print("\n== buyer pays + dispatches a job ==")
            BT = {"Authorization": f"Bearer {buyer_t}"}
            specs = expect("buyer list marketplace", c.get(f"{BASE}/marketplace/specs")).json()
            specs = specs if isinstance(specs, list) else specs.get("specs", [])
            mine = [s for s in specs if s.get("gpu_model") == "NVIDIA L4"]
            if not mine:
                bug("seller GPU is NOT visible in the marketplace after attest+heartbeat")
                pub_id = None
            else:
                pub_id = mine[0]["id"]
                trace(f"buyer sees spec public_id={pub_id}")

            tx_id = task_id = None
            if pub_id:
                expect("buyer quote", c.post(f"{BASE}/payments/quote", headers=BT,
                       json={"spec_id": pub_id, "estimated_seconds": 60}))
                az = expect("buyer authorize", c.post(f"{BASE}/payments/authorize", headers=BT,
                            json={"spec_id": pub_id, "estimated_seconds": 60}))
                tx_id = az.json().get("transaction_id")
                if tx_id:
                    # stand in for the client-side Stripe.js card confirm (fake gateway)
                    expect("buyer confirm card (sandbox)", c.post(
                        f"{BASE}/payments/{tx_id}/simulate-card", headers=BT))
                    expect("buyer confirm (mark_authorized)", c.post(
                        f"{BASE}/payments/{tx_id}/confirm", headers=BT))
                    expect("buyer reserve GPU", c.post(f"{BASE}/payments/{tx_id}/reserve", headers=BT))
                    dp = expect("buyer dispatch job", c.post(f"{BASE}/payments/{tx_id}/dispatch",
                        headers=BT, json={"task_type": "notebook", "code": "print('hello gpu')"}))
                    task_id = dp.json().get("task_id") or dp.json().get("task", {}).get("id")

            # -------- SELLER: claim + complete the buyer's paid job --------
            print("\n== seller executes the buyer's paid job ==")
            if tx_id:
                claim2 = expect("seller /jobs/next (paid)", c.get(f"{BASE}/jobs/next", headers=SK), (200, 204))
                if claim2.status_code == 200:
                    j2 = claim2.json()
                    task_id = task_id or j2.get("task_id")
                    expect("seller submit paid result", c.post(f"{BASE}/jobs/result", headers=SK,
                        json={"task_id": j2["task_id"], "status": "completed",
                              "result": "ok", **signed_proof("sha256:deadbeef")}))
                else:
                    bug("seller got NO job from /jobs/next after a paid dispatch "
                        "(paid dispatch not visible to the node?)")

            # -------- ADMIN: settle (meter -> capture -> transfer) --------
            print("\n== admin settles the transaction ==")
            if tx_id:
                AT = {"Authorization": f"Bearer {admin_t}"}
                expect("admin meter", c.post(f"{BASE}/admin/payments/{tx_id}/meter", headers=AT,
                       json={"actual_seconds": 57, "source": "agent"}), (200, 409))
                expect("admin capture", c.post(f"{BASE}/admin/payments/{tx_id}/capture",
                       headers=AT), (200, 409))
                expect("admin transfer", c.post(f"{BASE}/admin/payments/{tx_id}/transfer",
                       headers=AT), (200, 409))
                rc = expect("buyer receipt", c.get(f"{BASE}/payments/{tx_id}/receipt", headers=BT))
                pv = expect("final tx view", c.get(f"{BASE}/payments/{tx_id}", headers=BT)).json()
                trace(f"final tx status = {pv.get('status')}")

        # ---- summary ----
        print("\n================= SUMMARY =================")
        print(f"trace steps: {len(TRACE)}   bugs: {len(BUGS)}")
        for b in BUGS:
            print("  BUG: " + b)
        return 1 if BUGS else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        print("\n(server stopped)")


if __name__ == "__main__":
    sys.exit(main())
