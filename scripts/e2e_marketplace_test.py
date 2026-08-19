#!/usr/bin/env python3
"""e2e_marketplace_test.py — ONE-COMMAND real-Stripe-TEST + remote-GPU marketplace E2E.

Drives the whole path against a RUNNING Petabyte API and REAL Stripe TEST mode, with no manual
token/curl/JSON wrangling:

    buyer auth -> marketplace spec -> /payments/authorize (real Stripe TEST PaymentIntent,
    capture_method=manual) -> confirm the PI with the Stripe SDK (test card + return_url) ->
    POST /payments/{tx}/confirm (server verifies Stripe) -> reserve -> dispatch ONCE ->
    seller agent claims + runs a bounded GPU workload -> /jobs/result -> auto meter+capture ->
    poll GET -> verify capture / fee / seller-net -> unified proof (payment + signed compute
    receipt + payout) -> receipt + timeline -> redacted artifacts.

    With --settle-payout (and E2E_ADMIN_USERNAME/E2E_ADMIN_PASSWORD) it also drives the REAL
    provider payout leg — an admin transfer_to_seller = a Stripe TEST transfer to the seller's
    connected account — so the run proves buyer -> GPU -> PAYOUT -> receipt end to end. Without
    it, the seller net is HELD by design for the configured payout hold.

SAFETY — this runner NEVER touches live money and has NO override:
  * STRIPE_SECRET_KEY must start with sk_test_ (an sk_live_ key aborts immediately);
  * the created PaymentIntent must have livemode == false (else abort);
  * secrets (keys, client_secret, JWT, webhook secret) are never printed or written to artifacts.

Usage:
    python scripts/e2e_marketplace_test.py --api http://127.0.0.1:8000 --spec <public-spec-id>
    python scripts/e2e_marketplace_test.py --preflight-only          # == make e2e-preflight
Options: --buyer-username --estimated-seconds --gpu-test-seconds --poll-timeout
         --json-output PATH --keep-artifacts --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(ROOT, "artifacts")

# ------------------------------------------------------------------ secret hygiene
_SECRET_KEYS = ("client_secret", "secret_key", "stripe_secret_key", "access_token",
                "authorization", "password", "webhook_secret", "api_key", "jwt", "bearer")
_SECRET_RE = re.compile(r"(sk_(live|test)_[0-9A-Za-z]+|whsec_[0-9A-Za-z]+|Bearer\s+[\w.\-]+)")


def mask(s: str | None) -> str:
    """Show only the last 4 chars of a sensitive token, never the value."""
    if not s:
        return "(none)"
    s = str(s)
    return ("*" * max(0, len(s) - 4)) + s[-4:] if len(s) > 4 else "****"


def scrub(obj):
    """Recursively drop known-secret keys and redact secret-shaped strings, so artifacts can
    never carry a Stripe secret key, client_secret, JWT or webhook secret."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k.lower() in _SECRET_KEYS:
                continue
            out[k] = scrub(v)
        return out
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        return _SECRET_RE.sub("[REDACTED]", obj)
    return obj


class E2EAbort(Exception):
    """Fatal, pre-money safety/preflight failure — abort before creating any payment."""


class StageError(Exception):
    def __init__(self, stage, expected, actual, **ctx):
        self.stage, self.expected, self.actual, self.ctx = stage, expected, actual, ctx
        super().__init__(f"{stage}: expected {expected!r}, got {actual!r}")


# ------------------------------------------------------------------ Stripe key safety
def assert_stripe_test_key_or_abort() -> str:
    """Refuse to run without a Stripe TEST secret key. An sk_live_ key aborts with NO override —
    there is deliberately no --force and no env bypass."""
    sk = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not sk:
        raise E2EAbort("STRIPE_SECRET_KEY is not set. This runner needs a Stripe TEST key "
                       "(sk_test_…). It will never run without one.")
    if sk.startswith(("sk_live_", "rk_live_")):
        raise E2EAbort("STRIPE_SECRET_KEY is a LIVE key (sk_live_/rk_live_). This runner "
                       "REFUSES to run against live money. No override exists. Use a sk_test_ key.")
    if not sk.startswith(("sk_test_", "rk_test_")):
        raise E2EAbort(f"STRIPE_SECRET_KEY does not look like a Stripe TEST key "
                       f"(got prefix {sk[:8]!r}…). Refusing to run.")
    return sk


def assert_livemode_false_or_abort(pi: dict) -> None:
    if pi.get("livemode") is not False:
        raise E2EAbort(f"PaymentIntent livemode is {pi.get('livemode')!r} (expected False). "
                       "Aborting — this runner never operates on live PaymentIntents.")


# ------------------------------------------------------------------ tiny HTTP client
class Api:
    """HTTP client that owns buyer auth: it acquires the JWT internally, retries once on 401 by
    re-logging-in, and never prints the token (only a masked suffix)."""

    def __init__(self, base, username, password, verbose=False):
        import httpx
        self.base = base.rstrip("/")
        self.username = username
        self._password = password
        self.verbose = verbose
        self._token = None
        self._c = httpx.Client(timeout=30)

    def close(self):
        self._c.close()

    def _log(self, msg):
        if self.verbose:
            print("   ·", msg)

    def get_public(self, path, **kw):
        return self._c.get(self.base + path, **kw)

    def login(self):
        r = self._c.post(self.base + "/login",
                         data={"username": self.username, "password": self._password})
        if r.status_code != 200:
            raise StageError("AUTHENTICATION", "200 login", f"{r.status_code}",
                             hint="buyer login failed; check the account/password")
        self._token = r.json()["access_token"]
        self._log(f"buyer token acquired: {mask(self._token)}")

    def _auth(self):
        return {"Authorization": f"Bearer {self._token}"}

    def req(self, method, path, **kw):
        if self._token is None:
            self.login()
        headers = {**kw.pop("headers", {}), **self._auth()}
        r = getattr(self._c, method)(self.base + path, headers=headers, **kw)
        if r.status_code == 401:               # token expired mid-run -> re-login once
            self._log("token expired; re-logging in")
            self.login()
            headers = {**self._auth()}
            r = getattr(self._c, method)(self.base + path, headers=headers, **kw)
        return r


# ------------------------------------------------------------------ GPU workload
def gpu_workload_code(seconds: int) -> str:
    """A BOUNDED CUDA matmul loop (~`seconds` long) that generates measurable utilization and
    returns evidence. No infinite loop, no unbounded memory, no intentional OOM."""
    return (
        "import time, json\n"
        "ev = {'cuda_available': False, 'gpu_name': None, 'iterations': 0,\n"
        "      'duration_s': 0.0, 'peak_mem_mib': 0.0}\n"
        "try:\n"
        "    import torch\n"
        "    ev['cuda_available'] = bool(torch.cuda.is_available())\n"
        "    if ev['cuda_available']:\n"
        "        dev = 'cuda'\n"
        "        ev['gpu_name'] = torch.cuda.get_device_name(0)\n"
        "        n = 4096\n"
        "        a = torch.randn(n, n, device=dev); b = torch.randn(n, n, device=dev)\n"
        f"        deadline = time.time() + {int(seconds)}\n"
        "        t0 = time.time(); it = 0\n"
        "        while time.time() < deadline:\n"
        "            c = a @ b; torch.cuda.synchronize(); it += 1\n"
        "        ev['iterations'] = it\n"
        "        ev['duration_s'] = round(time.time() - t0, 2)\n"
        "        ev['peak_mem_mib'] = round(torch.cuda.max_memory_allocated()/1048576, 1)\n"
        "except Exception as e:\n"
        "    ev['error'] = type(e).__name__ + ': ' + str(e)[:200]\n"
        "print('E2E_GPU_EVIDENCE ' + json.dumps(ev))\n"
    )


# ------------------------------------------------------------------ preflight
def preflight(api: Api, spec_id: str) -> dict:
    """Fail BEFORE creating any payment. Returns a dict of check -> (status, detail)."""
    checks = {}

    def add(name, ok, detail=""):
        checks[name] = ("PASS" if ok else "FAIL", detail)
        return ok

    # API + DB health
    try:
        h = api.get_public("/healthz")
        add("API", h.status_code < 500, f"/healthz {h.status_code}")
    except Exception as e:  # noqa: BLE001
        add("API", False, f"unreachable: {type(e).__name__}")
    try:
        r = api.get_public("/readyz")
        add("Database", r.status_code < 500, f"/readyz {r.status_code}")
    except Exception as e:  # noqa: BLE001
        add("Database", False, f"unreachable: {type(e).__name__}")

    # Stripe key mode (runner side)
    try:
        assert_stripe_test_key_or_abort()
        add("Stripe key", True, "sk_test_…")
        add("Stripe mode", True, "TEST")
    except E2EAbort as e:
        add("Stripe key", False, str(e))
        add("Stripe mode", False, "not TEST")

    # Spec present in the PUBLIC marketplace == attested + available + seller payout-ready
    gpu_model = None
    try:
        ms = api.get_public("/marketplace/specs")
        specs = ms.json().get("specs", []) if ms.status_code == 200 else []
        hit = next((s for s in specs if s.get("id") == spec_id), None)
        add("GPU spec", hit is not None,
            "AVAILABLE" if hit else f"spec {spec_id} not listed (missing/unavailable/not "
            "payout-ready)")
        if hit:
            gpu_model = hit.get("gpu_model")
            add("Seller", (hit.get("available_units") or 0) >= 1,
                f"ONLINE, {hit.get('available_units')} unit(s)")
            add("Connect", True, "payout-ready (spec is publicly bookable)")
    except Exception as e:  # noqa: BLE001
        add("GPU spec", False, f"marketplace error: {type(e).__name__}")

    checks["_gpu_model"] = gpu_model
    return checks


def print_preflight(checks: dict):
    print("Preflight")
    for name, val in checks.items():
        if name.startswith("_"):
            continue
        status, detail = val
        print(f"  {name:<22}{status:<6}{('· ' + detail) if detail else ''}")


# ------------------------------------------------------------------ main flow
def run(args) -> dict:
    import httpx  # noqa: F401  (ensures dependency present early)
    # A real run REQUIRES a Stripe TEST key up front (aborts on a live/missing key). Preflight
    # defers the check so it can still render the table and REPORT the key state (Stripe key /
    # Stripe mode rows) instead of exiting before printing anything.
    sk = None if args.preflight_only else assert_stripe_test_key_or_abort()

    # unique, throwaway buyer — no hard-coded prod creds, password kept only in memory
    run_tag = os.urandom(4).hex()
    username = args.buyer_username or f"e2e_buyer_{run_tag}"
    password = "e2e-" + os.urandom(12).hex()

    api = Api(args.api, username, password, verbose=args.verbose)
    report = {"tool": "e2e_marketplace_test", "api": args.api, "spec_public_id": args.spec,
              "stripe_mode": "test", "stripe_livemode": None, "stages": {}, "result": "FAIL"}

    def stage(name, status, **extra):
        report["stages"][name] = {"status": status, **extra}

    try:
        # ---- preflight ----
        pf = preflight(api, args.spec)
        print_preflight(pf)
        report["preflight"] = {k: v for k, v in pf.items() if not k.startswith("_")}
        gpu_model = pf.get("_gpu_model")
        required = ["API", "Database", "Stripe key", "Stripe mode"]
        if getattr(args, "spec_provided", bool(args.spec)):
            required.append("GPU spec")     # only gate on the spec when one was actually given
        failed = [k for k, v in pf.items()
                  if not k.startswith("_") and k in required and v[0] == "FAIL"]
        if args.preflight_only:
            # Preflight REPORTS status; it never aborts (so `make e2e-preflight` without a key
            # or a SPEC still prints the table) — exit code reflects PREFLIGHT_OK vs _FAIL.
            report["result"] = "PREFLIGHT_OK" if not failed else "PREFLIGHT_FAIL"
            return report
        if failed:
            raise E2EAbort("preflight failed — refusing to create a payment. See the table above.")

        # ---- auth ---- (register a fresh throwaway buyer, then acquire the JWT internally)
        api._c.post(api.base + "/register_user",
                    json={"username": username, "password": password})
        api.login()
        stage("authentication", "PASS", buyer_token=mask(api._token), username=username)

        # ---- authorize (creates the real Stripe TEST PaymentIntent, manual capture) ----
        az = api.req("post", "/payments/authorize",
                     json={"spec_id": args.spec, "estimated_seconds": args.estimated_seconds})
        if az.status_code != 200:
            raise StageError("AUTHORIZE", "200", f"{az.status_code}", body=scrub(_safe_json(az)))
        azj = az.json()
        tx = azj["transaction_id"]
        pi_id = azj.get("payment_intent_id")
        report["transaction_public_id"] = tx
        report["payment_intent_id"] = pi_id
        stage("authorize", "PASS", transaction=tx, payment_intent=pi_id,
              authorization_minor=azj.get("authorization_amount"), currency=azj.get("currency"))

        # ---- confirm the PaymentIntent via the Stripe SDK (test card + return_url) ----
        import stripe
        stripe.api_key = sk
        # The runner holds the Stripe SECRET key, so it confirms the PI server-side BY ID — it
        # never needs (or stores) the client_secret, which is a browser-only credential.
        # Build the base URL FIRST, then fall back only when it is empty — otherwise `or`'s
        # loose binding makes the concatenation (never empty) win and yields a RELATIVE URL
        # that Stripe rejects. ret_url is always absolute.
        _base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        ret_url = (os.getenv("CONNECT_RETURN_URL")
                   or (_base + "/seller/payouts?stripe=return" if _base else None)
                   or "https://example.com/return")
        try:
            stripe.PaymentIntent.confirm(pi_id, payment_method="pm_card_visa",
                                         return_url=ret_url)
        except Exception as e:  # noqa: BLE001
            raise StageError("STRIPE_AUTHORIZATION", "requires_capture",
                             f"confirm error: {type(e).__name__}",
                             hint="PaymentIntent may need redirect handling / return_url",
                             stripe_object=pi_id, detail=str(e)[:200])
        pi = stripe.PaymentIntent.retrieve(pi_id)
        assert_livemode_false_or_abort(pi)
        report["stripe_livemode"] = bool(pi.get("livemode"))
        if pi.get("capture_method") != "manual":
            raise StageError("STRIPE_AUTHORIZATION", "capture_method=manual",
                             pi.get("capture_method"), stripe_object=pi_id)
        if pi.get("status") != "requires_capture":
            raise StageError("STRIPE_AUTHORIZATION", "requires_capture", pi.get("status"),
                             stripe_object=pi_id,
                             hint="test card did not authorize; check payment-method config")
        stage("stripe_authorization", "PASS", status="requires_capture",
              capture_method="manual", livemode=False)

        # ---- server-side confirmation (Petabyte re-verifies Stripe) ----
        cf = api.req("post", f"/payments/{tx}/confirm")
        _expect(cf, "PAYMENT_AUTHORIZED", "PETABYTE_CONFIRM", tx)
        stage("petabyte_confirm", "PASS", status="PAYMENT_AUTHORIZED")

        # ---- reserve ----
        rv = api.req("post", f"/payments/{tx}/reserve")
        _expect(rv, "GPU_RESERVED", "RESERVE", tx)
        stage("reserve", "PASS", status="GPU_RESERVED")

        # ---- dispatch ONCE (bounded GPU workload) ----
        dp = api.req("post", f"/payments/{tx}/dispatch",
                     json={"task_type": "notebook", "code": gpu_workload_code(args.gpu_test_seconds)})
        if dp.status_code != 200:
            raise StageError("DISPATCH", "200", f"{dp.status_code}", transaction=tx,
                             body=scrub(_safe_json(dp)))
        task_id = (dp.json() or {}).get("task_id")
        stage("dispatch", "PASS", status=dp.json().get("status"), task_id=task_id,
              note="dispatched ONCE; settlement is automatic — polling GET from here")

        # ---- poll GET until capture (NO second dispatch) ----
        deadline = time.monotonic() + args.poll_timeout
        last = None
        seen = []
        while time.monotonic() < deadline:
            pv = api.req("get", f"/payments/{tx}")
            st = pv.json().get("status") if pv.status_code == 200 else None
            if st and st != last:
                seen.append(st)
                print(f"   → {st}")
                last = st
            if st in ("PAYMENT_CAPTURED", "SELLER_TRANSFERRED", "COMPLETED"):
                break
            if st in ("CANCELLED", "REFUNDED", "CAPTURE_FAILED", "JOB_FAILED"):
                raise StageError("SETTLEMENT", "PAYMENT_CAPTURED", st, transaction=tx,
                                 task_id=task_id)
            time.sleep(2.0)
        report["observed_states"] = seen
        if last not in ("PAYMENT_CAPTURED", "SELLER_TRANSFERRED", "COMPLETED"):
            raise StageError("SETTLEMENT", "PAYMENT_CAPTURED", last or "timeout",
                             transaction=tx, task_id=task_id,
                             hint="seller agent may be offline or the workload timed out")

        # ---- receipt + timeline + unified proof + final view ----
        final = api.req("get", f"/payments/{tx}").json()
        receipt = _safe_json(api.req("get", f"/payments/{tx}/receipt"))
        timeline = _safe_json(api.req("get", f"/payments/{tx}/timeline"))
        proof = _safe_json(api.req("get", f"/payments/{tx}/proof"))
        cap = final.get("captured_amount") or 0
        fee = final.get("platform_fee_amount") or 0
        net = final.get("seller_net_amount") or 0
        stage("metering", "PASS", metering_seconds=final.get("metering_seconds"))
        stage("capture", "PASS", captured_minor=cap, authorization_minor=azj.get("authorization_amount"))
        ok_ident = (cap == fee + net)
        stage("accounting", "PASS" if ok_ident else "FAIL",
              platform_fee_minor=fee, seller_net_minor=net, identity_holds=ok_ident)
        # the compute half of the proof: a signed result the server re-verified live
        cproof = (proof.get("compute") or {}).get("proof") if isinstance(proof, dict) else None
        stage("compute_proof", "PASS" if (cproof and cproof.get("server_reverified")) else "WARN",
              server_reverified=(cproof or {}).get("server_reverified"),
              content_hash=(cproof or {}).get("content_hash_sha256"))
        report.update({"captured_minor": cap, "platform_fee_minor": fee,
                       "seller_net_minor": net, "metering_seconds": final.get("metering_seconds"),
                       "transferred_minor": final.get("transferred_amount", 0),
                       "gpu_model": gpu_model, "timeline": scrub(timeline),
                       "receipt": scrub(receipt), "proof": scrub(proof)})

        # ---- payout leg ----
        # By default the seller payout is HELD for the configured hold (PENDING BY DESIGN). Pass
        # --settle-payout WITH admin creds (E2E_ADMIN_USERNAME/PASSWORD) to drive the REAL
        # provider payout leg (transfer_to_seller -> a Stripe TEST transfer to the connected
        # account) so the demo proves buyer -> GPU -> payout -> receipt end to end.
        admin_user = os.getenv("E2E_ADMIN_USERNAME")
        admin_pass = os.getenv("E2E_ADMIN_PASSWORD")
        if args.settle_payout and admin_user and admin_pass:
            settled = _drive_payout(args.api, admin_user, admin_pass, tx)
            report["seller_settlement"] = settled
            stage("payout", "PASS" if settled.get("paid") else "FAIL",
                  transfer_id=mask(settled.get("stripe_transfer_id")),
                  transferred_minor=settled.get("transferred_minor"))
            report["proof"] = scrub(_safe_json(api.req("get", f"/payments/{tx}/proof")))
            payout_ok = bool(settled.get("paid"))
        else:
            report["seller_settlement"] = {
                "transferred_now": final.get("transferred_amount", 0),
                "status": ("PENDING BY DESIGN (held for the configured payout hold). Pass "
                           "--settle-payout with E2E_ADMIN_USERNAME/PASSWORD to drive the "
                           "provider payout leg in-session."),
            }
            payout_ok = True   # not requested -> not a failure

        report["result"] = "PASS" if (ok_ident and cap > 0 and payout_ok) else "FAIL"
        return report

    except (E2EAbort, StageError) as e:
        report["error"] = _describe_error(e)
        report["result"] = "ABORT" if isinstance(e, E2EAbort) else "FAIL"
        _release_on_failure(api, report)
        return report
    except Exception as e:  # noqa: BLE001 — an HTTP/JSON/shape error after /reserve must NOT
        # skip cleanup and leak the reservation. Record only the exception TYPE (never the
        # message — it could carry a secret) and run the same release path.
        report["error"] = {"stage": "UNEXPECTED", "actual": type(e).__name__}
        report["result"] = "FAIL"
        _release_on_failure(api, report)
        return report
    finally:
        api.close()


def _release_on_failure(api, report):
    """Best-effort cleanup so a FAILED run does not leak its reservation.

    POST /payments/{tx}/cancel frees the `stripe_reserved` booking + GPU unit and voids the Stripe
    hold. It succeeds (200) for a pre-dispatch tx AND for a dispatched tx that has since reached a
    terminal failure state (JOB_FAILED / CAPTURE_FAILED / DISPATCH_FAILED), which covers most E2E
    failure modes. Two cases this must still handle:

      * transient/unreachable API — a SINGLE request that can't reach the API must not give up
        and leak. We RETRY with bounded backoff.
      * dispatched and still actively running/settling — the endpoint returns 409 ("cannot
        cancel") because the job is genuinely in flight. We record that honestly (no fake
        "released") and rely on the server-side abandoned-reservation reaper
        (stripe_connect.reclaim_abandoned_reservations, run by the maintenance loop) to reclaim
        the unit once the tx fails or goes stale — so it is NOT held indefinitely.

    Only runs when a tx was actually created."""
    tx = report.get("transaction_public_id")
    if not tx:
        return                                   # failed before any authorization — nothing held
    last = None
    for attempt in range(5):
        try:
            r = api.req("post", f"/payments/{tx}/cancel")
            last = r.status_code
            if r.status_code == 200:
                report["cleanup"] = {"cancel_http": 200, "reservation_released": True}
                return
            if r.status_code == 409:
                # dispatched and still actively running/settling — the reaper reclaims it server-side.
                report["cleanup"] = {
                    "cancel_http": 409, "reservation_released": False, "needs_reclaim": True,
                    "note": "tx dispatched and still active; buyer cancel cannot release a running "
                            "job. The abandoned-reservation reaper reclaims the GPU unit once the "
                            "job fails or goes stale."}
                return
            # other 4xx/5xx may be transient — fall through and retry
        except Exception as ex:  # noqa: BLE001 — network error: retry, never mask the original failure
            last = f"error:{type(ex).__name__}"
        time.sleep(min(2 ** attempt, 8))
    # exhausted retries without a definitive release — report honestly; the reaper backstops it.
    report["cleanup"] = {
        "cancel_http": last, "reservation_released": False, "needs_reclaim": True,
        "note": "cancel did not succeed after retries; the server-side abandoned-reservation "
                "reaper will reclaim the GPU unit."}


def _drive_payout(base, admin_user, admin_pass, tx) -> dict:
    """Drive the REAL provider payout leg as an admin: POST /admin/payments/{tx}/transfer
    (transfer_to_seller -> a Stripe TEST transfer to the seller's connected account), then read
    the unified proof to report the settled payout. Never prints the admin token."""
    import httpx
    b = base.rstrip("/")
    try:
        with httpx.Client(timeout=30) as h:
            r = h.post(b + "/login", data={"username": admin_user, "password": admin_pass})
            if r.status_code != 200:
                return {"status": f"admin login failed (http {r.status_code}); payout not driven",
                        "transferred_minor": 0, "paid": False}
            ah = {"Authorization": f"Bearer {r.json()['access_token']}"}
            tr = h.post(b + f"/admin/payments/{tx}/transfer", headers=ah)
            if tr.status_code != 200:
                return {"status": f"transfer refused (http {tr.status_code}) — is the seller "
                                  f"payout-ready and the obligation claimable?",
                        "transferred_minor": 0, "paid": False, "http": tr.status_code}
            pf = h.get(b + f"/payments/{tx}/proof", headers=ah)
            po = ((pf.json() or {}).get("payout") or {}) if pf.status_code == 200 else {}
            return {"status": ("TRANSFERRED — real provider payout (Stripe TEST transfer)"
                              if po.get("paid") else "transfer attempted; see proof.payout"),
                    "transferred_minor": po.get("transferred_minor", 0),
                    "stripe_transfer_id": po.get("stripe_transfer_id"),
                    "obligation_state": po.get("obligation_state"),
                    "paid": bool(po.get("paid"))}
    except Exception as e:  # noqa: BLE001 — never leak; report the type only
        return {"status": f"payout leg error: {type(e).__name__}", "transferred_minor": 0,
                "paid": False}


def _safe_json(resp):
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"_status": getattr(resp, "status_code", None)}


def _expect(resp, want_status, stage, tx):
    if resp.status_code != 200 or (resp.json() or {}).get("status") != want_status:
        raise StageError(stage, want_status,
                         f"http {resp.status_code} / {(_safe_json(resp) or {}).get('status')}",
                         transaction=tx, body=scrub(_safe_json(resp)))


def _describe_error(e) -> dict:
    if isinstance(e, StageError):
        return {"stage": e.stage, "expected": e.expected, "actual": e.actual, **scrub(e.ctx)}
    return {"stage": "PREFLIGHT/SAFETY", "detail": str(e)}


# ------------------------------------------------------------------ report + artifacts
def render_text(r: dict) -> str:
    L = ["=" * 60, "PETABYTE REAL STRIPE TEST E2E", "=" * 60, ""]
    pf = r.get("preflight", {})
    L.append("Preflight")
    for k in ("API", "Database", "Stripe key", "Stripe mode", "Seller", "GPU spec", "Connect"):
        if k in pf:
            L.append(f"  {k:<22}{pf[k][0]}")
    st = r.get("stages", {})

    def line(label, key, extra=""):
        s = st.get(key, {})
        L.append(f"  {label:<22}{s.get('status', '—')}{extra}")

    L += ["", "Buyer"]
    line("Authentication", "authentication")
    L.append(f"  {'Transaction':<22}{r.get('transaction_public_id', '—')}")
    L += ["", "Payment authorization"]
    L.append(f"  {'PaymentIntent':<22}{r.get('payment_intent_id', '—')}")
    line("Stripe authorization", "stripe_authorization")
    L += ["", "Marketplace"]
    line("GPU reservation", "reserve")
    line("Job dispatch", "dispatch")
    L += ["", "Compute"]
    L.append(f"  {'GPU model':<22}{r.get('gpu_model') or 'NOT REPORTED'}")
    L += ["", "Metering / capture"]
    line("Metering", "metering")
    line("Stripe capture", "capture")

    def money(m):
        return f"${(m or 0)/100:.2f}"

    L += ["", "Accounting",
          f"  {'Authorization':<22}{money((st.get('authorize') or {}).get('authorization_minor'))}",
          f"  {'Captured':<22}{money(r.get('captured_minor'))}",
          f"  {'Platform fee':<22}{money(r.get('platform_fee_minor'))}",
          f"  {'Seller net':<22}{money(r.get('seller_net_minor'))}",
          f"  {'Invariants':<22}{(st.get('accounting') or {}).get('status', '—')}"]
    ss = r.get("seller_settlement", {})
    L += ["", "Seller settlement",
          f"  {'Transferred':<22}{money(ss.get('transferred_minor', ss.get('transferred_now')))}",
          f"  {'Stripe transfer':<22}{ss.get('stripe_transfer_id') or '—'}",
          f"  {'Obligation':<22}{ss.get('obligation_state', '—')}",
          f"  {'Status':<22}{ss.get('status', '—')}"]
    pr = r.get("proof") or {}
    cp = ((pr.get("compute") or {}).get("proof") or {}) if isinstance(pr, dict) else {}
    L += ["", "Unified proof",
          f"  {'Compute re-verified':<22}{cp.get('server_reverified', '—')}",
          f"  {'Content hash':<22}{(cp.get('content_hash_sha256') or '—')}",
          f"  {'Payout state':<22}{((pr.get('payout') or {}).get('hold_status', '—'))}"]
    L += ["", "Security",
          f"  {'Stripe live mode':<22}{'USED' if r.get('stripe_livemode') else 'NOT USED'}",
          f"  {'Payment bypass':<22}NONE",
          f"  {'Payout bypass':<22}NONE"]
    if r.get("error"):
        L += ["", "FAILURE", "  " + json.dumps(r["error"])]
    L += ["", "=" * 60, f"RESULT: {r.get('result')}", "=" * 60]
    return "\n".join(L)


def write_artifacts(r: dict, json_path: str | None):
    os.makedirs(ARTIFACTS, exist_ok=True)
    safe = scrub(r)
    jpath = json_path or os.path.join(ARTIFACTS, "REAL_E2E_REPORT.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2)
    tpath = os.path.join(ARTIFACTS, "REAL_E2E_REPORT.txt")
    with open(tpath, "w", encoding="utf-8") as f:
        f.write(render_text(safe) + "\n")
    return jpath, tpath


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Real Stripe TEST + remote GPU marketplace E2E")
    ap.add_argument("--api", default=os.getenv("E2E_API", "http://127.0.0.1:8000"))
    ap.add_argument("--spec", default=os.getenv("E2E_SPEC"))
    ap.add_argument("--buyer-username", default=os.getenv("E2E_BUYER"))
    ap.add_argument("--estimated-seconds", type=int, default=int(os.getenv("E2E_EST_SECONDS", "120")))
    ap.add_argument("--gpu-test-seconds", type=int, default=int(os.getenv("E2E_GPU_SECONDS", "45")))
    ap.add_argument("--poll-timeout", type=int, default=int(os.getenv("E2E_POLL_TIMEOUT", "300")))
    ap.add_argument("--json-output", default=None)
    ap.add_argument("--settle-payout", action="store_true",
                    help="drive the REAL provider payout leg after capture (needs "
                         "E2E_ADMIN_USERNAME/E2E_ADMIN_PASSWORD); default holds by design")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--keep-artifacts", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    args.spec_provided = bool(args.spec)     # remembered before the placeholder below
    if not args.spec and not args.preflight_only:
        print("error: --spec <public-spec-id> is required (or set E2E_SPEC)", file=sys.stderr)
        return 2
    if not args.spec:
        args.spec = "(preflight has no spec)"

    try:
        report = run(args)
    except E2EAbort as e:
        print(f"\nABORT: {e}", file=sys.stderr)
        return 3

    print("\n" + render_text(report))
    jpath, tpath = write_artifacts(report, args.json_output)
    print(f"\nArtifacts:\n  {os.path.relpath(jpath, ROOT)}\n  {os.path.relpath(tpath, ROOT)}")
    return 0 if report.get("result") in ("PASS", "PREFLIGHT_OK") else 1


if __name__ == "__main__":
    raise SystemExit(main())
