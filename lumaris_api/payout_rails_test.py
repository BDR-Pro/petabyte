"""payout_rails_test.py — irreversible payout rails are gated and fail CLOSED. Offline, no network.

USDC transfers can't be clawed back, so the Circle rail needs an explicit second switch
(CIRCLE_PAYOUTS_ENABLED=true) ON TOP of a live payout mode (PAYOUT_STUB=false). This proves:
  * stub/sandbox mode never touches a real rail;
  * a live USDC payout with the flag OFF fails closed (RailDisabled) — no crypto sent, ever;
  * turning the flag ON opens the gate (it then errors on missing creds, not on the gate) — so
    real USDC only moves when the operator has explicitly enabled it AND wired the wallet.

Run: python payout_rails_test.py
"""
import os

os.environ["PAYOUT_STUB"] = "true"
import payout_providers as pp          # noqa: E402
from payout_providers import RailDisabled  # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


_PAYOUT = {"id": 1, "kind": "usdc", "amount_usd": 10, "destination": "0xdeadbeef"}

# stub/sandbox: any kind returns the deterministic stub — no real rail, no gate needed.
os.environ["PAYOUT_STUB"] = "true"
os.environ.pop("CIRCLE_PAYOUTS_ENABLED", None)
_res = pp.get_provider("usdc").send(_PAYOUT)
ok("stub mode confirms USDC without touching a rail", _res.get("status") == "confirmed")

# live mode, Circle NOT enabled -> the send fails CLOSED (no USDC leaves).
os.environ["PAYOUT_STUB"] = "false"
os.environ.pop("CIRCLE_PAYOUTS_ENABLED", None)
_prov = pp.get_provider("usdc")
ok("live mode selects the real Circle provider", isinstance(_prov, pp.CircleUSDCProvider))
_disabled = False
try:
    _prov.send(_PAYOUT)
except RailDisabled:
    _disabled = True
ok("live USDC with CIRCLE_PAYOUTS_ENABLED unset FAILS CLOSED (no send)", _disabled)

# explicit 'false' is still closed
os.environ["CIRCLE_PAYOUTS_ENABLED"] = "false"
_disabled2 = False
try:
    pp.CircleUSDCProvider().send(_PAYOUT)
except RailDisabled:
    _disabled2 = True
ok("CIRCLE_PAYOUTS_ENABLED=false is still closed", _disabled2)

# flag ON -> the gate OPENS: it now fails on missing creds (KeyError), NOT on RailDisabled — proving
# the switch is what gates the rail, and that real USDC only flows once creds are also present.
os.environ["CIRCLE_PAYOUTS_ENABLED"] = "true"
os.environ.pop("CIRCLE_API_KEY", None)
_outcome = None
try:
    pp.CircleUSDCProvider().send(_PAYOUT)
except RailDisabled:
    _outcome = "still_disabled"
except Exception:
    _outcome = "gate_open_missing_creds"     # got past the gate, no HTTP (no creds) -> no money
ok("flag ON opens the gate (then errors on missing creds, not RailDisabled)",
   _outcome == "gate_open_missing_creds")

# process_payouts turns a disabled-rail send into a clean 'failed' (money never moves)
_statuses = {}
def _set_status(db, p, status, reason=None, provider_ref=None):
    _statuses[p.id] = (status, reason)
class _P:  # minimal payout row
    def __init__(s, pid): s.id = pid; s.method_id = pid; s.kind = "usdc"; s.amount_usd = 10
class _M:
    destination = "0xdeadbeef"
os.environ["PAYOUT_STUB"] = "false"
os.environ["CIRCLE_PAYOUTS_ENABLED"] = "false"
os.environ["SANCTIONS_SCREEN_PROVIDER"] = ""      # avoid the screen; test the rail gate itself
# screen() with no provider raises -> process_payouts would mark 'screening failed'; to isolate the
# rail gate, stub screen to pass.
pp.screen = lambda *a, **k: True                   # noqa: E731 — test shim
pp.process_payouts(None, [_P(7)], _set_status, lambda mid: _M())
ok("a disabled-rail payout is recorded FAILED, not sent", _statuses.get(7, ("", ""))[0] == "failed")

for k in ("PAYOUT_STUB", "CIRCLE_PAYOUTS_ENABLED", "SANCTIONS_SCREEN_PROVIDER"):
    os.environ.pop(k, None)

print(f"\n=== payout_rails: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
