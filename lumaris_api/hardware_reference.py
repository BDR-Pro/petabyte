"""hardware_reference.py — published hardware facts for the "buy a GPU and rent it" ROI math.

Two reference numbers per consumer GPU, both PUBLISHED (not invented, in the same spirit as the
FP16 TFLOPS table in gpu_benchmark.py):

  tdp_w       Total board power (W), vendor spec — used for the electricity cost of running jobs.
  msrp_usd    LAUNCH MSRP (USD) at announcement — a real published price, used only as an editable
              DEFAULT for the hardware cost. Street prices move constantly, so the UI lets the buyer
              override it and the affiliate "buy" link shows today's real price.

We deliberately scope this to the consumer/prosumer cards a person actually buys to rent (RTX 20/30/
40/50 + a few workstation Ax000). Datacenter parts (H100/A100/…) aren't bought by individuals to
list, so they're omitted here even though they have benchmarks.

The ROI math is intentionally simple and TRANSPARENT (every term is shown to the user):

    gross/hr (list)   = performance_reference_price(gpu)          # benchmark-anchored $/hr a buyer pays
    net/hr  (to you)  = gross/hr * (1 - platform_fee)             # after Petabyte's take
    power/hr (load)   = tdp_w/1000 * $per_kWh                      # electricity while a job runs
    net/hr (avg)      = (net/hr - power/hr) * utilization          # averaged over the day
    breakeven (days)  = hardware_cost / (net/hr_avg * 24)
    1-yr ROI %        = net/hr_avg * 24 * 365 / hardware_cost * 100

HONEST BY CONSTRUCTION: utilization is demand-dependent and NOT guaranteed; the number that drives
everything (gross/hr) is the platform's transparent benchmark reference, not a promise; and the
electricity model counts GPU load power during rented hours only — it excludes idle/host draw and
internet, which the UI states outright.
"""
from urllib.parse import quote_plus

# gpu_model (canonical key, matching gpu_benchmark._METRICS["tflops_fp16"]["ref"]) ->
#   tdp_w  : vendor Total Graphics/Board Power
#   msrp_usd: launch MSRP at announcement (USD)
GEAR = {
    # Ada / RTX 40 + Blackwell 50
    "RTX 5090":          {"tdp_w": 575, "msrp_usd": 1999},
    "RTX 4090":          {"tdp_w": 450, "msrp_usd": 1599},
    "RTX 4080 SUPER":    {"tdp_w": 320, "msrp_usd": 999},
    "RTX 4080":          {"tdp_w": 320, "msrp_usd": 1199},
    "RTX 4070 TI SUPER": {"tdp_w": 285, "msrp_usd": 799},
    "RTX 4070 TI":       {"tdp_w": 285, "msrp_usd": 799},
    "RTX 4070 SUPER":    {"tdp_w": 220, "msrp_usd": 599},
    "RTX 4070":          {"tdp_w": 200, "msrp_usd": 599},
    "RTX 4060 TI":       {"tdp_w": 160, "msrp_usd": 399},
    "RTX 4060":          {"tdp_w": 115, "msrp_usd": 299},
    # Ampere / RTX 30
    "RTX 3090 TI":       {"tdp_w": 450, "msrp_usd": 1999},
    "RTX 3090":          {"tdp_w": 350, "msrp_usd": 1499},
    "RTX 3080 TI":       {"tdp_w": 350, "msrp_usd": 1199},
    "RTX 3080":          {"tdp_w": 320, "msrp_usd": 699},
    "RTX 3070 TI":       {"tdp_w": 290, "msrp_usd": 599},
    "RTX 3070":          {"tdp_w": 220, "msrp_usd": 499},
    "RTX 3060 TI":       {"tdp_w": 200, "msrp_usd": 399},
    "RTX 3060":          {"tdp_w": 170, "msrp_usd": 329},
    # Turing / RTX 20 + Titan
    "TITAN RTX":         {"tdp_w": 280, "msrp_usd": 2499},
    "RTX 2080 TI":       {"tdp_w": 250, "msrp_usd": 999},
    "RTX 2080 SUPER":    {"tdp_w": 250, "msrp_usd": 699},
    "RTX 2080":          {"tdp_w": 215, "msrp_usd": 699},
    "RTX 2070 SUPER":    {"tdp_w": 215, "msrp_usd": 499},
    "RTX 2070":          {"tdp_w": 175, "msrp_usd": 499},
    "RTX 2060 SUPER":    {"tdp_w": 175, "msrp_usd": 399},
    "RTX 2060":          {"tdp_w": 160, "msrp_usd": 349},
    # Workstation Ampere (bought by some prosumers)
    "RTX A6000":         {"tdp_w": 300, "msrp_usd": 4650},
    "RTX A5000":         {"tdp_w": 230, "msrp_usd": 2250},
    "RTX A4000":         {"tdp_w": 140, "msrp_usd": 1000},
}


# Rest-of-build reference for the "whole PC" mode — the parts BESIDES the GPU that a modest but
# capable host needs (CPU, motherboard, 32GB RAM, ~850W PSU, 1TB NVMe, case/fans). These are
# EDITABLE reference estimates, not precise facts — the UI lets the buyer type their real numbers.
SYSTEM_COST_USD = 550     # typical rest-of-build (CPU+board+RAM+PSU+storage+case), USD
SYSTEM_WATTS = 100        # extra draw beyond the GPU under load (CPU+board+drives+fans), W


def _canonical(model):
    """Canonical GPU key (via the same normaliser the benchmark uses), or None."""
    try:
        import gpu_benchmark
        return gpu_benchmark.normalize_model(model)
    except Exception:
        return model if model in GEAR else None


def gear(model):
    """Published {tdp_w, msrp_usd} for a GPU, or None if we don't have reference specs for it."""
    key = _canonical(model)
    return GEAR.get(key) if key else None


def models():
    """GPU keys that have BOTH reference specs (here) and a benchmark-anchored price."""
    try:
        import pricing_engine
    except Exception:
        return []
    out = []
    for key in GEAR:
        if pricing_engine.performance_reference_price(key):
            out.append(key)
    return out


def buy_url(model, affiliate_tag=""):
    """Back-compat single Amazon link. Prefer buy_urls() for the multi-retailer list."""
    key = _canonical(model) or model
    url = "https://www.amazon.com/s?k=" + quote_plus(str(key) + " graphics card")
    tag = (affiliate_tag or "").strip()
    if tag:
        url += "&tag=" + quote_plus(tag)
    return url


def buy_urls(model, *, amazon_tag="", newegg_wrap=""):
    """Buy links across PC-hardware retailers. Each is a plain product SEARCH unless an affiliate
    hook is configured, so the feature degrades honestly when unset:

      * Amazon — appends the Associates ?tag= when `amazon_tag` is set.
      * Newegg — its affiliate program runs through a network (Rakuten/Impact), so we don't invent
        a tag: if `newegg_wrap` (a deeplink template containing "{url}") is configured we route the
        search through it; otherwise it's a plain Newegg search.

    Returns a list of {retailer, url, affiliate: bool}."""
    key = _canonical(model) or model
    q = str(key) + " graphics card"
    out = []
    amz = "https://www.amazon.com/s?k=" + quote_plus(q)
    tag = (amazon_tag or "").strip()
    if tag:
        amz += "&tag=" + quote_plus(tag)
    out.append({"retailer": "Amazon", "url": amz, "affiliate": bool(tag)})
    neg = "https://www.newegg.com/p/pl?d=" + quote_plus(q)
    wrap = (newegg_wrap or "").strip()
    if wrap and "{url}" in wrap:
        neg = wrap.replace("{url}", quote_plus(neg))
        out.append({"retailer": "Newegg", "url": neg, "affiliate": True})
    else:
        out.append({"retailer": "Newegg", "url": neg, "affiliate": False})
    return out


def roi_row(model, *, kwh_usd=0.12, hours_per_day=8.0, platform_fee=0.10, full_build=False,
            hardware_cost=None, system_cost_usd=None, system_watts=None):
    """One fully-transparent ROI row for a GPU, or None if we can't price/spec it.

    Models running the rig `hours_per_day` (adjustable, 0-24). `full_build=True` accounts for the
    WHOLE PC — it adds the rest-of-build cost and the extra system watts, not just the GPU. Every
    intermediate term is returned so the UI can SHOW the math and recompute live. `hardware_cost`
    overrides the total cost; `system_cost_usd`/`system_watts` override the rest-of-build refs."""
    import pricing_engine
    key = _canonical(model)
    g = GEAR.get(key) if key else None
    if not g:
        return None
    list_hr = pricing_engine.performance_reference_price(key)
    if not list_hr or list_hr <= 0:
        return None
    fee = max(0.0, min(0.9, float(platform_fee)))
    hours = max(0.0, min(24.0, float(hours_per_day)))
    kwh = max(0.0, float(kwh_usd))
    sys_cost_ref = float(system_cost_usd) if system_cost_usd is not None else float(SYSTEM_COST_USD)
    sys_watts_ref = float(system_watts) if system_watts is not None else float(SYSTEM_WATTS)
    gpu_cost = float(g["msrp_usd"])
    sys_cost = sys_cost_ref if full_build else 0.0
    watts = float(g["tdp_w"]) + (sys_watts_ref if full_build else 0.0)
    cost = float(hardware_cost) if (hardware_cost and float(hardware_cost) > 0) else (gpu_cost + sys_cost)
    net_price_hr = list_hr * (1.0 - fee)                 # you keep per rented hour, before power
    power_hr = (watts / 1000.0) * kwh                    # electricity per rented (running) hour
    net_hr = net_price_hr - power_hr                     # net per rented hour
    net_day = net_hr * hours                             # only earns while actually rented
    breakeven_days = (cost / net_day) if net_day > 0 else None
    roi_year_pct = ((net_day * 365.0) / cost * 100.0) if cost > 0 else None
    tflops = None
    try:
        import gpu_benchmark
        _k, tflops = gpu_benchmark.reference_value(key, "tflops_fp16")
    except Exception:
        pass
    return {
        "gpu_model": key,
        "benchmark_tflops_fp16": (round(float(tflops), 1) if tflops else None),
        "hours_per_day": round(hours, 2),
        "full_build": bool(full_build),
        # power
        "gpu_tdp_w": g["tdp_w"],
        "system_watts_ref": round(sys_watts_ref),        # extra watts added in full-build mode
        "watts_total": round(watts),
        # cost
        "gpu_cost_usd": round(gpu_cost, 2),              # GPU launch MSRP (editable default)
        "system_cost_ref": round(sys_cost_ref, 2),       # rest-of-build ref added in full-build mode
        "hardware_cost_usd": round(cost, 2),             # total used for breakeven (override-aware)
        # earnings
        "list_price_per_hr": round(float(list_hr), 2),   # what a buyer pays
        "net_price_per_hr": round(net_price_hr, 4),      # you keep per rented hr, before power
        "power_cost_per_hr": round(power_hr, 4),
        "net_per_hr": round(net_hr, 4),                  # per rented hour, after power
        "net_per_day": round(net_day, 2),
        "net_per_month": round(net_day * 30.0, 2),
        "net_per_year": round(net_day * 365.0, 2),
        "breakeven_days": (round(breakeven_days, 1) if breakeven_days is not None else None),
        "breakeven_months": (round(breakeven_days / 30.0, 1) if breakeven_days is not None else None),
        "roi_year_pct": (round(roi_year_pct, 1) if roi_year_pct is not None else None),
        "profitable": net_day > 0,
    }
