"""sanctions_test.py — the free/public OFAC sanctions screen is real and fails CLOSED.

Pure + offline (a tiny fixture address file; no network, no vendor). Proves:
  * comprehensively-embargoed countries are recognised (+ extendable via env);
  * stub mode passes; live mode with no provider fails closed;
  * OFAC 'ofac' provider blocks a sanctioned country and a listed USDC wallet, allows a clean one;
  * USDC screening with no address list configured FAILS CLOSED (never sends unscreened);
  * bank/gift-card under OFAC fail closed (address list can't screen a name);
  * the refresh parser extracts digital-currency addresses from OFAC sdn.xml.

Run: python sanctions_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import sanctions          # noqa: E402
import payout_providers as pp   # noqa: E402
from payout_providers import ScreeningUnavailable  # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def raises(fn):
    try:
        fn()
        return False
    except ScreeningUnavailable:
        return True


# clean env
for k in ("PAYOUT_STUB", "SANCTIONS_SCREEN_PROVIDER", "OFAC_SDN_ADDRESSES_FILE",
          "SANCTIONS_EXTRA_COUNTRIES"):
    os.environ.pop(k, None)
sanctions.reset_cache()

# ---- sanctioned jurisdictions ----
ok("Iran/North Korea/Cuba/Syria are sanctioned", all(sanctions.is_sanctioned_country(c) for c in ("IR", "KP", "CU", "SY")))
ok("US/GB/DE are not sanctioned", not any(sanctions.is_sanctioned_country(c) for c in ("US", "GB", "DE")))
ok("country match is case-insensitive", sanctions.is_sanctioned_country("ir"))
ok("None/empty country is not sanctioned", not sanctions.is_sanctioned_country(None) and not sanctions.is_sanctioned_country(""))
os.environ["SANCTIONS_EXTRA_COUNTRIES"] = "ru, xx"
ok("extra sanctioned countries extend the list via env", sanctions.is_sanctioned_country("RU") and sanctions.is_sanctioned_country("XX"))
os.environ.pop("SANCTIONS_EXTRA_COUNTRIES", None)

# ---- stub mode passes (sandbox) ----
os.environ["PAYOUT_STUB"] = "true"
ok("stub mode passes any destination", pp.screen("usdc", "anything") is True)
os.environ.pop("PAYOUT_STUB", None)

# ---- live mode, no provider -> fail closed ----
ok("live mode with no provider fails closed", raises(lambda: pp.screen("usdc", "0xabc")))

# ---- OFAC provider ----
os.environ["SANCTIONS_SCREEN_PROVIDER"] = "ofac"

# a sanctioned country is blocked on ANY rail (return False, not a raise)
ok("OFAC blocks a payout to a sanctioned country", pp.screen("bank", "acct-1", country="IR") is False)

# USDC with NO address list -> fail closed (can't screen -> don't send)
sanctions.reset_cache()
ok("USDC with no OFAC list configured fails closed", raises(lambda: pp.screen("usdc", "0xclean")))

# configure a tiny OFAC address fixture
fd, addr_file = tempfile.mkstemp(prefix="ofac-test-", suffix=".txt")
with os.fdopen(fd, "w") as f:
    f.write("# fixture\n0xBADWALLET1234\n1SanctionedBTCwalletZZZ\n")
os.environ["OFAC_SDN_ADDRESSES_FILE"] = addr_file
sanctions.reset_cache()

ok("OFAC address list is now available", sanctions.ofac_addresses_available())
ok("a LISTED USDC wallet is blocked", pp.screen("usdc", "0xBADWALLET1234") is False)
ok("USDC address match is case-insensitive", pp.screen("usdc", "0xbadwallet1234") is False)
ok("a CLEAN USDC wallet is allowed", pp.screen("usdc", "0xCleanWallet9999") is True)

# bank / gift-card under OFAC (address list can't screen a name) -> fail closed
ok("bank under OFAC fails closed (needs name screening)", raises(lambda: pp.screen("bank", "acct-9")))
ok("gift_card under OFAC fails closed (needs name screening)", raises(lambda: pp.screen("gift_card", "a@b.com")))

# ---- a named-but-unimplemented vendor -> fail closed ----
os.environ["SANCTIONS_SCREEN_PROVIDER"] = "chainalysis"
ok("an unimplemented vendor fails closed", raises(lambda: pp.screen("usdc", "0xCleanWallet9999")))

# ---- refresh parser: extract crypto addresses from OFAC sdn.xml ----
import refresh_ofac_addresses as refresh  # noqa: E402
_SDN = b"""<?xml version="1.0"?>
<sdnList xmlns="http://tempuri.org/sdnList.xsd">
  <sdnEntry><uid>1</uid><idList>
    <id><uid>10</uid><idType>Digital Currency Address - XBT</idType><idNumber>1SanctionedBTCwalletZZZ</idNumber></id>
    <id><uid>11</uid><idType>Digital Currency Address - ETH</idType><idNumber>0xBADWALLET1234</idNumber></id>
    <id><uid>12</uid><idType>Email Address</idType><idNumber>x@y.z</idNumber></id>
  </idList></sdnEntry>
</sdnList>"""
addrs = refresh.extract_addresses(_SDN)
ok("refresh parser extracts BOTH digital-currency addresses", addrs == {"1SanctionedBTCwalletZZZ", "0xBADWALLET1234"})
ok("refresh parser excludes non-crypto identifiers (email)", "x@y.z" not in addrs)

os.remove(addr_file)
for k in ("SANCTIONS_SCREEN_PROVIDER", "OFAC_SDN_ADDRESSES_FILE"):
    os.environ.pop(k, None)
sanctions.reset_cache()

print(f"\n=== sanctions: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
