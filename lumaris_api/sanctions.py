"""sanctions.py — free, public OFAC sanctions screening (no paid vendor).

Two controls that need NO third-party account or credentials:

  1. **Comprehensively-sanctioned jurisdictions.** OFAC country embargo programs — a payout
     whose destination country is embargoed is blocked. ISO-3166 alpha-2.
  2. **OFAC SDN digital-currency addresses.** A crypto (USDC) payout to a wallet on OFAC's
     Specially Designated Nationals list is blocked. The address list is refreshed from OFAC's
     PUBLIC SDN data by `scripts/refresh_ofac_addresses.py` into `OFAC_SDN_ADDRESSES_FILE`;
     screening reads that local file (offline, cached).

This is a **baseline**, not a full compliance program. It deliberately does NOT do name / fuzzy /
PEP / adverse-media matching against the SDN — those need a vendor (Chainalysis / TRM / Persona /
Sumsub) and are wired via `SANCTIONS_SCREEN_PROVIDER` in payout_providers.screen(). What it does is
exactly the minimum OFAC control a US fintech must run, using data that is free and public today.
"""
from __future__ import annotations

import os
import threading

# OFAC comprehensively-sanctioned jurisdictions (country embargo programs), ISO-3166 alpha-2:
# Cuba, Iran, North Korea, Syria. Regional programs (Crimea / so-called DNR-LNR) are not ISO
# country codes and are handled by region checks upstream, not here. Extend at deploy time with
# SANCTIONS_EXTRA_COUNTRIES (comma-separated) as the program list changes.
_BASE_SANCTIONED = frozenset({"CU", "IR", "KP", "SY"})


def sanctioned_countries() -> frozenset:
    extra = os.getenv("SANCTIONS_EXTRA_COUNTRIES", "")
    codes = {c.strip().upper() for c in extra.split(",") if c.strip()}
    return _BASE_SANCTIONED | codes


def is_sanctioned_country(code) -> bool:
    """True if the ISO-3166 alpha-2 country is under a comprehensive OFAC embargo."""
    return bool(code) and str(code).strip().upper() in sanctioned_countries()


# --- OFAC SDN digital-currency addresses (public list, refreshed into a local file) ---
_addr_lock = threading.Lock()
_addr_cache = None            # cached lowercased address set
_addr_cache_path = None


def _load_addresses(path: str) -> set:
    out = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # tolerate "ADDR  # note" and "network,address" CSV-ish lines — take the token that
            # looks like an address (longest field), lowercased for case-insensitive match.
            token = max((p.strip() for p in s.replace(",", " ").split()), key=len, default="")
            if token:
                out.add(token.lower())
    return out


def ofac_addresses_available() -> bool:
    """True only if an OFAC address file is configured AND present — so crypto screening can
    fail CLOSED (refuse the payout) when it is not, rather than silently passing."""
    p = os.getenv("OFAC_SDN_ADDRESSES_FILE")
    return bool(p and os.path.exists(p))


def ofac_addresses() -> set:
    """Cached set of lowercased sanctioned crypto addresses from OFAC_SDN_ADDRESSES_FILE."""
    global _addr_cache, _addr_cache_path
    path = os.getenv("OFAC_SDN_ADDRESSES_FILE")
    if not path or not os.path.exists(path):
        return set()
    with _addr_lock:
        if _addr_cache is not None and _addr_cache_path == path:
            return _addr_cache
        try:
            _addr_cache = _load_addresses(path)
        except Exception:
            _addr_cache = set()
        _addr_cache_path = path
        return _addr_cache


def is_sanctioned_address(address) -> bool:
    """True if the crypto address is on the OFAC SDN digital-currency list."""
    if not address:
        return False
    return str(address).strip().lower() in ofac_addresses()


def reset_cache() -> None:
    """Test/ops hook: drop the cached address set so an updated file is re-read."""
    global _addr_cache, _addr_cache_path
    with _addr_lock:
        _addr_cache = None
        _addr_cache_path = None
