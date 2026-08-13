"""pricing_engine_test.py — the pricing recommender is value-anchored, explainable, and honest.

Pure and offline: no DB, no network. Run: python pricing_engine_test.py
"""
import pricing_engine as pe

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---- cloud reference lookup: like-for-like, or nothing (no invented discounts) ----
ok("H100 has a cloud reference", pe.cloud_reference_for("NVIDIA H100 80GB") == 12.29)
ok("RTX 4090 matches on the bare model", pe.cloud_reference_for("RTX 4090") == 0.80)
ok("longest key wins (a100 not a10)", pe.cloud_reference_for("A100 SXM") == 4.10)
ok("unknown GPU has NO reference (not a fake one)", pe.cloud_reference_for("Foocard 9000") is None)
ok("None / empty model -> no reference", pe.cloud_reference_for(None) is None and pe.cloud_reference_for("") is None)

# ---- anchor: cloud on-demand, discounted. "neutral" = agent_verified (no premium, no discount)
# at 50% demand so the only factor in play is the anchor itself. ----
r = pe.recommend(10.0, utilization=0.5, trust_level="agent_verified",
                 cloud_discount=0.60, demand_sensitivity=0.50)
ok("anchor is cloud x discount", r["anchor"] == 6.0 and r["anchor_source"] == "cloud")
ok("at neutral 50% demand + no other factors, price == anchor", r["recommended_price"] == 6.0)
ok("savings vs cloud is reported", r["savings_vs_cloud_pct"] == 40.0)

# ---- no cloud reference -> fall back to the seller's own band, and SAY SO ----
rb = pe.recommend(None, min_price=1.0, max_price=3.0, utilization=0.5)
ok("no cloud ref -> anchor on band midpoint", rb["anchor"] == 2.0 and rb["anchor_source"] == "seller_band")
ok("no cloud ref -> no savings figure (honest)", rb["savings_vs_cloud_pct"] is None)
ok("no cloud ref -> explanation says so", "no cloud reference" in rb["explanation"].lower())

# ---- demand moves the price around neutral ----
hot = pe.recommend(10.0, utilization=1.0, cloud_discount=0.60, demand_sensitivity=0.50)
cold = pe.recommend(10.0, utilization=0.0, cloud_discount=0.60, demand_sensitivity=0.50)
ok("busy GPU class prices higher than idle", hot["recommended_price"] > cold["recommended_price"])
_dm = next(f for f in hot["factors"] if f["factor"] == "demand")
ok("full demand multiplier is 1 + sensitivity*0.5", _dm["multiplier"] == 1.25)

# ---- verified performance / trust ----
consistent = pe.recommend(10.0, utilization=0.5, benchmark_verdict="consistent")
flagged = pe.recommend(10.0, utilization=0.5, benchmark_verdict="implausibly_low")
selfrep = pe.recommend(10.0, utilization=0.5, trust_level="self_reported")
ok("a benchmark-consistent card earns a premium", consistent["recommended_price"] > 6.0)
ok("a flagged (implausible) benchmark is discounted", flagged["recommended_price"] < 6.0)
ok("self-reported (unproven) is discounted below neutral", selfrep["recommended_price"] < 6.0)
ok("consistent prices above self-reported", consistent["recommended_price"] > selfrep["recommended_price"])

# ---- premiums: confidential, region, reputation ----
conf = pe.recommend(10.0, utilization=0.5, confidential=True)
ok("confidential (TEE) commands a premium", conf["recommended_price"] > 6.0)
ok("reputation 100 prices above reputation 0",
   pe.recommend(10.0, utilization=0.5, reputation=100)["recommended_price"] >
   pe.recommend(10.0, utilization=0.5, reputation=0)["recommended_price"])

# ---- clamps ----
# always below cloud even when every premium stacks
maxed = pe.recommend(10.0, utilization=1.0, benchmark_verdict="consistent",
                     confidential=True, region_verified=True, reputation=100)
ok("never priced at or above the cloud reference", maxed["recommended_price"] < 10.0)
ok("cloud cap is recorded as a factor when it bites",
   any(f["factor"] == "cloud_cap" for f in maxed["factors"]))

# seller's own band is a hard ceiling/floor
ceil = pe.recommend(10.0, utilization=1.0, benchmark_verdict="consistent",
                    confidential=True, reputation=100, min_price=0.5, max_price=2.0)
ok("clamped to the seller's max price", ceil["recommended_price"] == 2.0)
ok("seller ceiling recorded as a factor", any(f["factor"] == "seller_ceiling" for f in ceil["factors"]))
floor = pe.recommend(10.0, utilization=0.0, trust_level="self_reported",
                     min_price=5.0, max_price=9.0)
ok("never below the seller's min price", floor["recommended_price"] >= 5.0)
ok("seller floor recorded as a factor", any(f["factor"] == "seller_floor" for f in floor["factors"]))
ok("price is never negative", pe.recommend(0.0, current_price=0.0)["recommended_price"] >= 0.0)

# ---- performance-anchored reference price: MONOTONIC in the FP16 benchmark ----
# The core fairness rule: a slower GPU is never priced above a faster one.
ok("RTX 2060 has a benchmark reference price", pe.performance_reference_price("RTX 2060") is not None)
ok("a slower GPU (2060) is cheaper than a faster one (4080)",
   pe.performance_reference_price("RTX 2060") < pe.performance_reference_price("RTX 4080"))
ok("4080 is cheaper than 4090", pe.performance_reference_price("RTX 4080") < pe.performance_reference_price("RTX 4090"))
ok("an unknown GPU has no benchmark reference price", pe.performance_reference_price("Foocard 9000") is None)

_cat = pe.catalog()
ok("catalog lists many GPU models", len(_cat) >= 20)
ok("catalog is sorted by benchmark ascending",
   all(_cat[i]["benchmark_tflops_fp16"] <= _cat[i + 1]["benchmark_tflops_fp16"] for i in range(len(_cat) - 1)))
ok("catalog reference price is NON-DECREASING along the benchmark order (slower never dearer)",
   all(_cat[i]["reference_price_per_hour"] <= _cat[i + 1]["reference_price_per_hour"] for i in range(len(_cat) - 1)))
ok("every catalog row carries a benchmark + a reference price",
   all(r["benchmark_tflops_fp16"] and r["reference_price_per_hour"] for r in _cat))

# recommend() anchors on the performance reference when given, and reports it
_pr = pe.recommend(0.80, perf_reference=pe.performance_reference_price("RTX 4090"),
                   utilization=0.5, trust_level="agent_verified")
ok("recommend anchors on the performance reference when provided", _pr["anchor_source"] == "performance")
ok("recommend echoes the perf reference + still reports cloud savings",
   _pr["perf_reference"] == pe.performance_reference_price("RTX 4090") and _pr["savings_vs_cloud_pct"] is not None)
ok("performance-anchored explanation names the benchmark", "benchmark" in _pr["explanation"].lower())
# two GPUs, same everything except benchmark -> the faster one is recommended higher
_slow = pe.recommend(None, perf_reference=pe.performance_reference_price("RTX 2060"), utilization=0.5, trust_level="agent_verified")
_fast = pe.recommend(None, perf_reference=pe.performance_reference_price("RTX 4090"), utilization=0.5, trust_level="agent_verified")
ok("all else equal, the faster GPU is recommended at a higher price",
   _fast["recommended_price"] > _slow["recommended_price"])

# ---- the smoke invariant: A100 auto-price node, band [0.5, 2.0], stays inside the band ----
a100 = pe.recommend(pe.cloud_reference_for("A100"), utilization=0.0,
                    trust_level="self_reported", reputation=100,
                    min_price=0.5, max_price=2.0, current_price=9.0)
ok("A100 auto-price lands inside [0.5, 2.0]", 0.5 <= a100["recommended_price"] <= 2.0)

# ---- explainability: every price shows its work ----
ok("recommendation always carries a plain-language explanation",
   isinstance(r["explanation"], str) and len(r["explanation"]) > 0)
ok("every multiplier factor carries a 'why'",
   all(f.get("why") for f in consistent["factors"]))
ok("recommendation carries an honest 'you set the final price' note",
   "you set the final price" in r["note"].lower())

print(f"\n=== pricing_engine: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
