"""Normalized seller-payout country-capability model.

Single source of truth: config/payout_country_capabilities.json (the frontend and the
coverage script read this, never a hardcoded country array). This module loads it,
answers capability queries, enforces sanctions, and applies the STRICT definition of
"active" coverage so the coverage number is honest.

A country/rail row counts as ACTIVE coverage ONLY when ALL hold:
  * implementation_status == "implemented"      (the adapter genuinely exists)
  * availability_status   == "active"           (not preview/planned/pending)
  * approved is True (or provider_approval_required is False)
  * the country is not in the sanctioned block list

Anything else (pending_provider_approval, preview, planned, not_implemented, blocked)
does NOT count. This is what stops an unimplemented adapter or an unapproved preview
product from inflating coverage.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "config", "payout_country_capabilities.json")


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def load_dataset(path: str = None) -> dict:
    return _load(path or os.getenv("PAYOUT_CAPABILITIES_PATH", _DEFAULT_PATH))


def sanctioned_countries(path: str = None) -> set:
    return set(load_dataset(path).get("sanctioned_blocked", []))


def is_sanctioned(country_code: str, path: str = None) -> bool:
    return (country_code or "").upper() in sanctioned_countries(path)


def _row_is_active(row: dict, sanctioned: set) -> bool:
    if row["country_code"].upper() in sanctioned:
        return False
    if row.get("implementation_status") != "implemented":
        return False
    if row.get("availability_status") != "active":
        return False
    if row.get("provider_approval_required") and not row.get("approved"):
        return False
    return True


def capabilities_for(country_code: str, recipient_type: str = None,
                     currency: str = None, path: str = None) -> list:
    """All capability rows for a country (optionally filtered by recipient type /
    currency), each annotated with whether it is currently ACTIVE. Sanctioned countries
    return an empty list — they are never payable."""
    cc = (country_code or "").upper()
    if is_sanctioned(cc, path):
        return []
    sanctioned = sanctioned_countries(path)
    out = []
    for row in load_dataset(path)["countries"]:
        if row["country_code"].upper() != cc:
            continue
        if recipient_type and recipient_type not in row.get("recipient_types", []):
            continue
        if currency and currency.lower() not in [c.lower() for c in row.get("supported_currencies", [])]:
            continue
        r = dict(row)
        r["is_active"] = _row_is_active(row, sanctioned)
        out.append(r)
    return out


def active_rails_for(country_code: str, recipient_type: str = None,
                     currency: str = None, path: str = None) -> list:
    """Only the rows that genuinely provide payout TODAY (active + implemented +
    approved + not sanctioned). Empty means the seller is unsupported/waitlisted."""
    return [r for r in capabilities_for(country_code, recipient_type, currency, path)
            if r["is_active"]]


def coverage_summary(path: str = None) -> dict:
    """The honest coverage breakdown used by the CI coverage check and the UI. Counts
    DISTINCT countries by their best status; ACTIVE is the strict verified number."""
    data = load_dataset(path)
    sanctioned = sanctioned_countries(path)
    by_country_status = {}          # cc -> best status bucket
    active_bank, active_stable, multi = set(), set(), {}
    preview, pending, planned, not_impl = set(), set(), set(), set()

    for row in data["countries"]:
        cc = row["country_code"].upper()
        multi.setdefault(cc, 0)
        if _row_is_active(row, sanctioned):
            by_country_status.setdefault(cc, "active")
            by_country_status[cc] = "active"
            multi[cc] += 1
            if row.get("bank_payout_supported"):
                active_bank.add(cc)
            if row.get("stablecoin_payout_supported"):
                active_stable.add(cc)
        else:
            st = row.get("availability_status")
            impl = row.get("implementation_status")
            if impl != "implemented":
                not_impl.add(cc)
            elif st == "preview":
                preview.add(cc)
            elif st == "pending_provider_approval":
                pending.add(cc)
            elif st == "planned":
                planned.add(cc)

    active = {cc for cc, s in by_country_status.items() if s == "active"}
    # a country is "active" overall if any rail is active; demote it from the lesser sets
    for s in (preview, pending, planned, not_impl):
        s -= active
    stable_only = {cc for cc in active_stable if cc not in active_bank}
    multi_rail = {cc for cc, n in multi.items() if cc in active and n > 1}
    return {
        "platform_country": data["_meta"].get("platform_country"),
        "verified_at": data["_meta"].get("verified_at"),
        "total_countries_in_dataset": len({r["country_code"].upper() for r in data["countries"]}),
        "active_countries": sorted(active),
        "active_count": len(active),
        "active_bank_countries": sorted(active_bank),
        "active_stablecoin_only_countries": sorted(stable_only),
        "multi_rail_countries": sorted(multi_rail),
        "preview_countries": sorted(preview),
        "pending_provider_approval_countries": sorted(pending),
        "planned_countries": sorted(planned),
        "not_implemented_countries": sorted(not_impl),
        "blocked_sanctioned_countries": sorted(sanctioned),
        "sources": data["_meta"].get("sources", {}),
    }
