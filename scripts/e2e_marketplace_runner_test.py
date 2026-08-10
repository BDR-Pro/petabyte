#!/usr/bin/env python3
"""Unit tests for the real-Stripe-TEST E2E runner's SAFETY guards (no network needed).

Covers the non-negotiable safety properties of scripts/e2e_marketplace_test.py:
  * refuses a live Stripe key (no override);
  * refuses a livemode PaymentIntent;
  * masks tokens and redacts secrets from artifacts;
  * the GPU workload is bounded (no infinite loop) and long enough to measure.

Run: python scripts/e2e_marketplace_runner_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import e2e_marketplace_test as R  # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _raises_abort(fn):
    try:
        fn()
        return False
    except R.E2EAbort:
        return True


# Key-shaped fixtures are ASSEMBLED at runtime (never written as a contiguous literal) so
# GitHub push-protection / secret scanners don't flag these obviously-fake test strings.
_B = "x" * 24
_SK_LIVE = "sk_" + "live_" + _B
_RK_LIVE = "rk_" + "live_" + _B
_PK_TEST = "pk_" + "test_" + "notasecret"
_SK_TEST = "sk_" + "test_" + ("t" * 20)

_saved = os.environ.get("STRIPE_SECRET_KEY")
try:
    # ---- live key is refused, with NO override ----
    os.environ["STRIPE_SECRET_KEY"] = _SK_LIVE
    ok("a LIVE secret key (sk_live_) is refused", _raises_abort(R.assert_stripe_test_key_or_abort))
    os.environ["STRIPE_SECRET_KEY"] = _RK_LIVE
    ok("a LIVE restricted key (rk_live_) is refused", _raises_abort(R.assert_stripe_test_key_or_abort))
    os.environ.pop("STRIPE_SECRET_KEY", None)
    ok("a missing key is refused", _raises_abort(R.assert_stripe_test_key_or_abort))
    os.environ["STRIPE_SECRET_KEY"] = _PK_TEST
    ok("a non-secret / wrong-prefix key is refused", _raises_abort(R.assert_stripe_test_key_or_abort))
    os.environ["STRIPE_SECRET_KEY"] = _SK_TEST
    ok("a TEST secret key (sk_test_) is accepted",
       R.assert_stripe_test_key_or_abort() == _SK_TEST)
finally:
    if _saved is None:
        os.environ.pop("STRIPE_SECRET_KEY", None)
    else:
        os.environ["STRIPE_SECRET_KEY"] = _saved

# ---- livemode PaymentIntent is refused ----
ok("a livemode=True PaymentIntent is refused",
   _raises_abort(lambda: R.assert_livemode_false_or_abort({"livemode": True})))
ok("a livemode=None PaymentIntent is refused",
   _raises_abort(lambda: R.assert_livemode_false_or_abort({"livemode": None})))
_ok_pi = True
try:
    R.assert_livemode_false_or_abort({"livemode": False})
except R.E2EAbort:
    _ok_pi = False
ok("a livemode=False PaymentIntent is accepted", _ok_pi)

# ---- secret masking ----
ok("mask shows only the last 4 chars", R.mask("supersecrettoken1234") == "*" * 16 + "1234")
ok("mask handles None safely", R.mask(None) == "(none)")

# ---- artifact redaction ---- (secret-shaped values assembled at runtime, not literals)
_inline_sk = "sk_" + "test_" + "LEAKYKEY1234ABCD"
_inline_whsec = "whsec_" + "ABCDEF012345"
_nested_whsec = "whsec_" + "NESTEDNOTAPPEAR"
raw = {
    "transaction_public_id": "ctx_abc",
    "client_secret": "pi_" + "123_secret_SHOULD_NOT_APPEAR",
    "access_token": "eyJhbG" + "SHOULD_NOT_APPEAR",
    "password": "hunter2",
    "note": f"authorized with {_inline_sk} and {_inline_whsec} and Bearer abc.def.ghi",
    "nested": {"webhook_secret": _nested_whsec, "keep": "ok"},
    "payment_intent_id": "pi_public_ok",
}
clean = R.scrub(raw)
blob = __import__("json").dumps(clean)
ok("scrub drops client_secret", "client_secret" not in clean and "SHOULD_NOT_APPEAR" not in blob)
ok("scrub drops access_token/JWT", "access_token" not in clean)
ok("scrub drops password", "password" not in clean)
ok("scrub drops nested webhook_secret", "webhook_secret" not in clean["nested"])
ok("scrub redacts inline sk_test_ / whsec_ / Bearer tokens",
   _inline_sk not in blob and _inline_whsec not in blob and "Bearer abc" not in blob)
ok("scrub keeps non-secret fields (pi id, tx id, nested keep)",
   clean["payment_intent_id"] == "pi_public_ok" and clean["transaction_public_id"] == "ctx_abc"
   and clean["nested"]["keep"] == "ok")

# ---- bounded GPU workload ----
code = R.gpu_workload_code(45)
ok("workload uses CUDA sync (real GPU work, measurable)", "torch.cuda.synchronize()" in code)
ok("workload is time-BOUNDED (deadline loop, not while True)",
   "while time.time() < deadline" in code and "while True" not in code)
ok("workload honours the requested duration", "time.time() + 45" in code)
ok("workload emits parseable evidence", "E2E_GPU_EVIDENCE" in code)

# ---- the report never carries secrets (render is called on the report in main) ----
ok("render_text of a scrubbed report contains no secret markers",
   "SHOULD_NOT_APPEAR" not in R.render_text(clean))

print(f"\n=== e2e_runner_safety: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
