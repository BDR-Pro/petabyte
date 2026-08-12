"""hardware_reference_test.py — the "buy a GPU and rent it" ROI math is honest and correct. Offline.

Proves:
  * every term of the ROI is derived, not invented: earnings come from the benchmark-anchored
    reference price, minus the platform fee and electricity, scaled by utilization;
  * breakeven = cost / net-per-day, and it lengthens as utilization drops / electricity rises;
  * a slower card never shows a higher $/hr you-keep than a faster one (monotonic, inherited
    from the price engine);
  * affiliate links carry the tag only when configured, and are plain searches otherwise;
  * at zero utilization nothing is profitable (breakeven None) — no fantasy payback.

Run: python hardware_reference_test.py
"""
import hardware_reference as hw
import pricing_engine

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# --- gear lookup ---
ok("known consumer GPUs have published specs (tdp + msrp)",
   hw.gear("RTX 4090") is not None and hw.gear("RTX 4090")["tdp_w"] > 0
   and hw.gear("RTX 4090")["msrp_usd"] > 0)
ok("an unknown GPU has no reference specs (None, never a guess)", hw.gear("Banana 9000") is None)
ok("model normalisation matches the benchmark table (free-text resolves)",
   hw.gear("nvidia geforce rtx 4090") is not None)
ok("every priced ROI model also has a benchmark reference price",
   len(hw.models()) > 0 and all(pricing_engine.performance_reference_price(m) for m in hw.models()))

# --- ROI math is exact and transparent ---
r = hw.roi_row("RTX 4090", kwh_usd=0.12, utilization=0.5, platform_fee=0.10)
_list = pricing_engine.performance_reference_price("RTX 4090")
_net_price = _list * 0.90
_power = (450 / 1000.0) * 0.12
_net_hr = (_net_price - _power) * 0.5
_be_days = hw.gear("RTX 4090")["msrp_usd"] / (_net_hr * 24)
ok("you-keep/hr = list price x (1 - fee)", abs(r["net_price_per_hr"] - _net_price) < 1e-6)
ok("power/hr = tdp_kW x $/kWh", abs(r["power_cost_per_hr"] - _power) < 1e-6)
ok("net/hr averages (keep - power) over the day at utilization", abs(r["net_per_hr"] - _net_hr) < 1e-6)
ok("net/day = net/hr x 24", abs(r["net_per_day"] - _net_hr * 24) < 0.01)   # stored at 2 dp
ok("breakeven(days) = hardware cost / net-per-day", abs(r["breakeven_days"] - round(_be_days, 1)) < 0.2)
ok("1-yr ROI% = net/day x 365 / cost x 100",
   abs(r["roi_year_pct"] - round(_net_hr * 24 * 365 / hw.gear("RTX 4090")["msrp_usd"] * 100, 1)) < 0.5)

# --- direction of the levers (sanity, not magic) ---
lo = hw.roi_row("RTX 4090", kwh_usd=0.12, utilization=0.25, platform_fee=0.10)
hi = hw.roi_row("RTX 4090", kwh_usd=0.12, utilization=0.75, platform_fee=0.10)
ok("lower utilization -> LONGER breakeven (payback depends on real demand)",
   lo["breakeven_days"] > hi["breakeven_days"])
dear = hw.roi_row("RTX 4090", kwh_usd=0.40, utilization=0.5, platform_fee=0.10)
ok("pricier electricity -> smaller net/hr (power is really subtracted)",
   dear["net_per_hr"] < r["net_per_hr"])
ok("hardware_cost override replaces the MSRP default",
   hw.roi_row("RTX 4090", hardware_cost=800)["hardware_cost_usd"] == 800.0)

# --- zero utilization is honest: nothing pays back ---
z = hw.roi_row("RTX 4090", utilization=0.0)
ok("0% utilization -> not profitable, breakeven None (no fantasy payback)",
   z["profitable"] is False and z["breakeven_days"] is None)

# --- monotonic you-keep/hr: a slower card is never worth more per hour than a faster one ---
_rows = [hw.roi_row(m, utilization=1.0, platform_fee=0.0) for m in hw.models()]
_rows = [x for x in _rows if x]
_rows.sort(key=lambda x: x["benchmark_tflops_fp16"] or 0)
_mono = all(_rows[i]["net_price_per_hr"] <= _rows[i + 1]["net_price_per_hr"] + 1e-9
            for i in range(len(_rows) - 1))
ok("you-keep/hr is monotonic in FP16 benchmark (slower GPU never worth more per hour)", _mono)

# --- affiliate links: tag only when configured; honest plain search otherwise ---
ok("buy link carries the Associates tag when configured",
   "tag=petabyte-20" in hw.buy_url("RTX 4090", "petabyte-20"))
ok("buy link is a plain (non-monetised) search when no tag is set",
   "tag=" not in hw.buy_url("RTX 4090", "") and "amazon.com" in hw.buy_url("RTX 4090", ""))
ok("the GPU model is url-encoded into the search",
   "RTX+4090" in hw.buy_url("RTX 4090", ""))

print(f"\n=== hardware_reference: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
