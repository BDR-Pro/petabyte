"""earnings.py — honest earnings forecast for a seller node.

Sellers want to know "what will I make running my agent?" The dishonest way is to invent a single
demand number. The honest way (this module): give the DEFINITIVE part exactly — net take-home per
hour = price × (1 − platform fee) — and the demand-dependent part as an ESTIMATE at several
utilization levels, so the seller sees the shape and picks their own expectation. When the node
opts into idle mining, the trickle it earns while unrented is added in.

Pure functions — no DB, no network — so both the web page and the agent can call it and it is
trivially testable.
"""
from __future__ import annotations


def forecast(price_per_hour, take_rate, *, idle_daily_usd=None, idle_enabled=False,
             util_levels=(0.25, 0.50, 0.75)) -> dict:
    """Earnings forecast for one node. Returns the definitive net/hour plus per-utilization
    estimates (daily/monthly, split rented vs idle-mining) and a compact headline range."""
    price = max(0.0, float(price_per_hour or 0))
    take = min(max(float(take_rate or 0), 0.0), 1.0)
    net_hr = round(price * (1 - take), 4)
    idle = max(0.0, float(idle_daily_usd or 0)) if idle_enabled else 0.0

    def _at(util):
        util = min(max(float(util), 0.0), 1.0)
        rented = net_hr * 24 * util
        idle_share = idle * (1 - util)          # the miner earns only while the GPU is unrented
        daily = rented + idle_share
        return {"utilization": round(util, 2),
                "daily_usd": round(daily, 2), "monthly_usd": round(daily * 30, 2),
                "rented_daily_usd": round(rented, 2), "idle_daily_usd": round(idle_share, 2)}

    rows = [_at(u) for u in util_levels]
    return {
        "price_per_hour": round(price, 2),
        "platform_take_rate": take,
        "net_per_hour": net_hr,                  # the one number that is NOT a guess
        "idle_mining_daily_usd": round(idle, 2),
        "idle_enabled": bool(idle_enabled),
        "estimates": rows,
        "headline": {                            # compact range for small UIs (CLI / desktop)
            "low_daily_usd": rows[0]["daily_usd"] if rows else 0.0,
            "high_daily_usd": rows[-1]["daily_usd"] if rows else 0.0,
        },
        "note": "Estimate based on your price and typical utilization; actual earnings depend on demand.",
    }
