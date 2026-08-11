"""product_analytics_test.py — the PostHog funnel mirror is correct, safe, and off-by-default.

Asserts: only funnel events are captured; the payload uses the right distinct id + human
label; secrets/PII are stripped; it is a no-op unless configured; and it never raises.
No network — the sender is monkeypatched. Run: python product_analytics_test.py
"""
import os
import types

import product_analytics as pa

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


os.environ["POSTHOG_API_KEY"] = "phc_test_key"
os.environ["PRODUCT_ANALYTICS_ENABLED"] = "true"

# ---------------------------------------------------------------- build_payload (pure)
ok("a non-funnel event builds NO payload (most telemetry is ignored)",
   pa.build_payload("http.request.completed", {"user_id": 1}) is None)

p = pa.build_payload("user.signed_up", {"user_id": 42, "referred": True})
ok("a funnel event maps to a human PostHog label", p and p["event"] == "user signed up")
ok("distinct id is the numeric user id", p["distinct_id"] == "42")
ok("safe properties pass through + event_name is tagged",
   p["properties"]["referred"] is True and p["properties"]["event_name"] == "user.signed_up")

# distinct-id preference order: user_id > buyer_id > seller_id
ok("distinct id prefers user_id over seller_id",
   pa.build_payload("job.dispatched", {"seller_id": 9, "user_id": 3})["distinct_id"] == "3")
ok("falls back to seller_id when no user/buyer id",
   pa.build_payload("seller.gpu.detected", {"seller_id": 7})["distinct_id"] == "7")
ok("falls back to 'anonymous' when no id at all",
   pa.build_payload("user.signed_up", {})["distinct_id"] == "anonymous")

# ---------------------------------------------------------------- secrets/PII are stripped
secret_props = pa.build_payload("wallet.funded", {
    "user_id": 5, "amount": 100, "password": "hunter2", "email": "a@b.com",
    "api_key": "sk_live_x", "signature": "deadbeef", "attest_pubkey": "AAAA"})["properties"]
ok("password / email / api_key / signature / pubkey are NEVER sent",
   not any(k in secret_props for k in ("password", "email", "api_key", "signature", "attest_pubkey")))
ok("non-sensitive properties (amount) still pass through", secret_props.get("amount") == 100)

# ---------------------------------------------------------------- off by default (no key)
os.environ.pop("POSTHOG_API_KEY", None)
ok("with no POSTHOG_API_KEY, capture is a no-op", pa.maybe_capture("user.signed_up", {"user_id": 1}) is False)
os.environ["POSTHOG_API_KEY"] = "phc_test_key"
os.environ["PRODUCT_ANALYTICS_ENABLED"] = "false"
ok("PRODUCT_ANALYTICS_ENABLED=false hard-disables capture",
   pa.maybe_capture("user.signed_up", {"user_id": 1}) is False)
os.environ["PRODUCT_ANALYTICS_ENABLED"] = "true"

# ---------------------------------------------------------------- dispatch (network stubbed)
_sent = []
pa._send = lambda payload: _sent.append(payload)                      # capture instead of POST
pa.threading = types.SimpleNamespace(                                 # run synchronously
    Thread=lambda target, args, daemon: types.SimpleNamespace(start=lambda: target(*args)))
ok("a configured funnel event IS dispatched", pa.maybe_capture("job.execution.completed", {"user_id": 8}) is True)
ok("the dispatched payload carries the api key + label + distinct id",
   _sent and _sent[-1]["event"] == "job completed" and _sent[-1]["api_key"] == "phc_test_key"
   and _sent[-1]["distinct_id"] == "8")
ok("a non-funnel event is still NOT dispatched even when configured",
   pa.maybe_capture("ratelimit.blocked", {"user_id": 8}) is False)

# ---------------------------------------------------------------- never raises
pa._send = lambda payload: (_ for _ in ()).throw(RuntimeError("network down"))
ok("a sender that raises never surfaces to the caller",
   pa.maybe_capture("transaction.completed", {"user_id": 1}) in (True, False))

print(f"\n=== product_analytics: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
