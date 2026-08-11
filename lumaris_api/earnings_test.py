"""earnings_test.py — the seller earnings forecast is correct + honest. Pure, offline.

Run: python earnings_test.py
"""
import earnings as e

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# definitive part: net take-home per hour = price * (1 - take)
f = e.forecast(2.0, 0.10, idle_enabled=False)
ok("net per hour is price x (1 - platform take)", f["net_per_hour"] == 1.8)
ok("forecast gives estimates at several utilization levels", len(f["estimates"]) == 3)
ok("utilization levels default to 25/50/75%",
   [r["utilization"] for r in f["estimates"]] == [0.25, 0.50, 0.75])

_mid = next(r for r in f["estimates"] if r["utilization"] == 0.50)
ok("at 50% utilization: daily = net/hr x 24 x 0.5", _mid["daily_usd"] == round(1.8 * 24 * 0.5, 2))
ok("monthly = daily x 30", _mid["monthly_usd"] == round(_mid["daily_usd"] * 30, 2))
ok("headline range low<=high", f["headline"]["low_daily_usd"] <= f["headline"]["high_daily_usd"])
ok("forecast carries an honest 'depends on demand' note", "demand" in f["note"].lower())

# idle mining adds a trickle ONLY while unrented, and ONLY when opted in
fi = e.forecast(2.0, 0.10, idle_daily_usd=2.0, idle_enabled=True)
ok("idle mining is included when enabled", fi["idle_mining_daily_usd"] == 2.0)
_lo = next(r for r in fi["estimates"] if r["utilization"] == 0.25)
ok("at 25% util the idle trickle is 75% of the idle daily", _lo["idle_daily_usd"] == round(2.0 * 0.75, 2))
ok("idle mining is 0 when NOT opted in", e.forecast(2.0, 0.1, idle_daily_usd=2.0, idle_enabled=False)["idle_mining_daily_usd"] == 0.0)

# clamps: never negative, take rate bounded to [0,1]
ok("a negative price clamps to $0 net", e.forecast(-5, 0.1)["net_per_hour"] == 0.0)
ok("a take rate > 1 clamps (net never negative)", e.forecast(2.0, 1.5)["net_per_hour"] == 0.0)

print(f"\n=== earnings: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
