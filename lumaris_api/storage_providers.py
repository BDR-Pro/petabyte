"""Storage-network earnings adapter. Petabyte runs ONE account per decentralized storage network
(Storj / BTFS / Sia); each seller node contributes as `pbdisk-<spec_id>`, so per-node earnings map
1:1 to sellers (exactly like the NiceHash `pb-<spec_id>` worker model). This returns SETTLED
per-node USD for a period; `db.reconcile_disk_earnings` credits sellers' unified balances.

Stub for tests (`STORAGE_STUB=true`). The real path is functional code that calls the provider's
payout/earnings API — it needs a provider account + credentials in env to run, and is intentionally
NOT wired to a live account here (same honesty as nicehash.py / the Circle payout adapter).
"""
import json
import os


def _stub_earnings(period: str) -> dict:
    """Deterministic per-node earnings for offline tests. `STORAGE_STUB_EARNINGS` may override with
    a JSON map {node_id: amount_usd}. Default: empty (no fake money unless a test asks for it)."""
    raw = os.getenv("STORAGE_STUB_EARNINGS")
    if raw:
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
    else:
        data = {}
    provider = os.getenv("DISK_PROVIDER", "storj")
    return {node: {"period": period, "amount": float(amt), "provider": provider}
            for node, amt in data.items()}


def get_node_earnings(period: str) -> dict:
    """SETTLED per-node USD for `period` -> {node_id: {"period","amount","provider"}}.

    Offline/tests: `STORAGE_STUB=true` returns `_stub_earnings`. Real: query the configured
    provider's earnings API (per-node, filtered to the `pbdisk-` prefix) — requires provider
    credentials. Kept as an explicit adapter seam; it never invents earnings."""
    if os.getenv("STORAGE_STUB", "").lower() == "true":
        return _stub_earnings(period)
    provider = os.getenv("DISK_PROVIDER", "storj").lower()
    # TODO(adapter): wire the real per-node earnings pull for the configured provider. This needs a
    # funded platform account + API credentials (see docs/DISK_RENTAL.md). Until then, refuse to
    # guess — return nothing rather than fabricate a payout.
    raise RuntimeError(
        f"storage earnings for provider={provider!r} not configured: set STORAGE_STUB=true for "
        f"tests, or provide provider credentials + implement the adapter (docs/DISK_RENTAL.md).")
