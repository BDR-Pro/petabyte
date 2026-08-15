"""priority_country_test.py — per-capability verification of the priority-market watch list.

Offline, deterministic, no DB. Proves the 20-country priority layer (a thin WATCH list on
top of config/payout_country_capabilities.json) resolves each market to its REAL payout
capability and never over-claims: nothing is 'active' unless it passes the strict rule,
embargoed markets are blocked, and markets with no rail read 'not_supported' (not a silent
default). The list lives in _meta.priority_countries — this asserts the resolver, not a
hardcoded expectation table, so it can't be gamed by editing the dataset to pass.

Run: python priority_country_test.py
"""
import payout_capabilities as cap

PASSES = FAILS = 0


def ok(label, cond):
    global PASSES, FAILS
    print(("PASS " if cond else "FAIL ") + label)
    if cond:
        PASSES += 1
    else:
        FAILS += 1


# ---------------------------------------------------------------- the watch list itself
prio = cap.priority_countries()
ok("priority list has exactly 20 markets", len(prio) == 20)
ok("priority codes are unique", len(set(prio)) == len(prio))
ok("priority codes are upper-case ISO-alpha-2",
   all(len(c) == 2 and c.isalpha() and c == c.upper() for c in prio))

m = cap.priority_capability_matrix()
ok("matrix covers exactly the priority list (one record per market)",
   [c["country_code"] for c in m["countries"]] == prio)
ok("matrix priority_count matches the list length", m["priority_count"] == len(prio))

# ---------------------------------------------------------------- honesty invariants
_VALID = {"active", "pending_provider_approval", "preview", "planned",
          "not_implemented", "not_supported", "blocked_sanctioned"}
ok("every market resolves to a KNOWN status (no 'unknown')",
   all(c["status"] in _VALID for c in m["countries"]))

# active_today is the ONLY 'payable now' flag and must agree with status=='active'
ok("active_today is set iff status=='active'",
   all(c["active_today"] == (c["status"] == "active") for c in m["countries"]))

# the shipped dataset is honestly zero-active until a real end-to-end payout is verified
ok("no priority market is falsely marked payable today (honest 0 active)",
   m["active_today_count"] == 0
   and all(not c["active_today"] for c in m["countries"]))

# bucket counts reconcile with the per-country records
_status_total = sum(len(v) for v in m["status_buckets"].values())
ok("status buckets partition the whole list (counts reconcile)",
   _status_total == m["priority_count"])
ok("capable_count == markets with a rail on file",
   m["capable_count"] == sum(1 for c in m["countries"] if c["has_capability"]))

# ---------------------------------------------------------------- per-outcome coverage
byc = {c["country_code"]: c for c in m["countries"]}

# (1) a sanctioned priority market is BLOCKED and never payable, regardless of any row
ok("RU (embargoed) is blocked_sanctioned and not payable",
   byc["RU"]["status"] == "blocked_sanctioned" and byc["RU"]["sanctioned"]
   and not byc["RU"]["active_today"] and byc["RU"]["rail"] is None)
ok("a blocked market exposes no capability rows via capabilities_for",
   cap.capabilities_for("RU") == [])

# (2) a Stripe-Connect market resolves to the connect rail + its local settlement currency
ok("US resolves to the stripe connect_express rail in usd (pending approval, honest)",
   byc["US"]["rail"] == "connect_express" and byc["US"]["provider"] == "stripe"
   and "usd" in byc["US"]["settlement_currencies"]
   and byc["US"]["has_capability"] and not byc["US"]["active_today"])
ok("every connect market is bank-payout, pending_provider_approval, not active today",
   all(byc[c]["bank_payout_supported"] and byc[c]["status"] == "pending_provider_approval"
       and not byc[c]["active_today"]
       for c in ("GB", "DE", "CA", "FR", "NL", "SE", "AU", "JP", "SG", "PL",
                 "ES", "IT", "BR", "AE") if c in byc))

# (3) a market with NO rail on file reads not_supported (fail-honest, not a US default)
for cc in ("IN", "KR"):
    ok(f"{cc} has no rail on file -> not_supported (no silent default)",
       byc[cc]["status"] == "not_supported" and not byc[cc]["has_capability"]
       and byc[cc]["rail"] is None and not byc[cc]["active_today"])

# (4) a planned-but-unbuilt rail reads not_implemented and is not payable
ok("NG (global-payouts) is not_implemented and not payable today",
   byc["NG"]["status"] == "not_implemented" and byc["NG"]["rail"] == "global_payouts"
   and not byc["NG"]["active_today"])
ok("KE (Circle USDC stablecoin) is not_implemented and not payable today",
   byc["KE"]["status"] == "not_implemented" and byc["KE"]["stablecoin_payout_supported"]
   and not byc["KE"]["active_today"])

# ---------------------------------------------------------------- single-country resolver
ok("country_capability agrees with the matrix for a sampled market",
   cap.country_capability("US") == byc["US"])
ok("country_capability is case-insensitive on the code",
   cap.country_capability("us")["country_code"] == "US")
ok("an off-list country still resolves honestly (not_supported, never a crash)",
   cap.country_capability("ZZ")["status"] == "not_supported")

# names surface for off-dataset priority markets (via _meta fallback), not just codes
ok("off-dataset priority markets still carry a display name",
   byc["IN"]["country_name"] == "India" and byc["KR"]["country_name"] == "South Korea")


print(f"\n=== priority_country: {PASSES} passed, {FAILS} failed ===")
raise SystemExit(1 if FAILS else 0)
