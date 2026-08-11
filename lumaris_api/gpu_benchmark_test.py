"""gpu_benchmark_test.py — the multi-benchmark GPU authenticity check.

Compare measured scores (FP16 matmul TFLOPS, Blender Open Data, Cinebench, PugetBench) to
the PUBLIC reference data for the CLAIMED GPU model and get an honest verdict. The
hardware-invariant FP16 metric may freeze payouts; the render/video metrics are advisory
(flag a mismatch, never auto-freeze). Pure functions — no GPU, no network, no DB.

Run: python gpu_benchmark_test.py
"""
import gpu_benchmark as gb   # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---------------------------------------------------------------- normalize_model (shared)
ok("normalize strips vendor prefix + memory suffix (H100)",
   gb.normalize_model("NVIDIA H100 80GB HBM3") == "H100")
ok("normalize handles A100-SXM4-80GB dash form", gb.normalize_model("NVIDIA A100-SXM4-80GB") == "A100")
ok("normalize does NOT confuse A10 with A100",
   gb.normalize_model("NVIDIA A10") == "A10" and gb.normalize_model("NVIDIA A100") == "A100")
ok("normalize GeForce RTX 4090", gb.normalize_model("GeForce RTX 4090") == "RTX 4090")
ok("normalize packed 'rtx4090'", gb.normalize_model("rtx4090") == "RTX 4090")
ok("normalize folds H100 board variants (PCIe/SXM) into H100", gb.normalize_model("H100 PCIe") == "H100")
ok("normalize unknown card -> None", gb.normalize_model("FooGPU 9000") is None)

# ---------------------------------------------------------------- reference lookups
ok("reference_peak (FP16) resolves H100 to its datasheet peak", gb.reference_peak("nvidia h100") == ("H100", 989.0))
ok("reference_value(blender_optix) resolves an RTX 4090", gb.reference_value("RTX 4090", "blender_optix")[1] == 12500.0)
ok("metric_meta exposes the public source", "opendata.blender.org" in gb.metric_meta("blender_optix")["source"])
ok("known metrics include tflops + blender + cinebench + puget",
   {"tflops_fp16", "blender_optix", "cinebench_2024_gpu",
    "pugetbench_resolve", "pugetbench_premiere"}.issubset(set(gb.KNOWN_METRICS)))

# ---------------------------------------------------------------- FP16 = the FREEZING metric
c = gb.classify("H100", 720, metric="tflops_fp16")   # ~73% of peak — a real H100 matmul
ok("a genuine H100 FP16 score is CONSISTENT", c["verdict"] == "consistent" and not c["fraud"])
ok("FP16 metric declares itself freezing", c["freezes"] is True)
low = gb.classify("H100", 55, metric="tflops_fp16")   # T4-class number under an H100 listing
ok("claiming H100 but measuring T4-class TFLOPS -> implausibly_low", low["verdict"] == "implausibly_low")
ok("a GROSS FP16 over-claim is FRAUD (freeze)", low["fraud"] is True)
soft = gb.classify("H100", 250, metric="tflops_fp16")   # below floor, above fraud floor
ok("a mildly-low FP16 reading is implausibly_low but NOT fraud", soft["verdict"] == "implausibly_low" and soft["fraud"] is False)

# ---------------------------------------------------------------- Blender = ADVISORY (never freezes)
b = gb.classify("RTX 4090", 12000, metric="blender_optix")
ok("a genuine RTX 4090 Blender score is CONSISTENT", b["verdict"] == "consistent")
ok("Blender metric declares itself advisory (non-freezing)", b["freezes"] is False)
blow = gb.classify("RTX 4090", 1500, metric="blender_optix")   # 3080-and-below territory
ok("a 4090 that renders like a weak card -> implausibly_low", blow["verdict"] == "implausibly_low")
ok("but a render benchmark NEVER sets the fraud/freeze flag", blow["fraud"] is False)
bhi = gb.classify("RTX 3070", 12000, metric="blender_optix")
ok("a 3070 reporting 4090-class Blender -> suspiciously_high (no freeze)",
   bhi["verdict"] == "suspiciously_high" and bhi["fraud"] is False)

# ---------------------------------------------------------------- Cinebench + PugetBench recognised
ok("Cinebench 2024 GPU consistent for a 4090",
   gb.classify("RTX 4090", 32000, metric="cinebench_2024_gpu")["verdict"] == "consistent")
ok("PugetBench Resolve consistent for a 4090",
   gb.classify("RTX 4090", 11500, metric="pugetbench_resolve")["verdict"] == "consistent")
ok("PugetBench Premiere is advisory (non-freezing)",
   gb.classify("RTX 4090", 500, metric="pugetbench_premiere")["fraud"] is False)

# ---------------------------------------------------------------- NiceHash mining hashrate (bandwidth proxy)
ok("a genuine RTX 4090 Ethash hashrate (~120 MH/s) is CONSISTENT",
   gb.classify("RTX 4090", 120, metric="hashrate_ethash_mhs")["verdict"] == "consistent")
ok("a 4090 reporting a 3050-class hashrate -> implausibly_low (advisory, never freezes)",
   gb.classify("RTX 4090", 25, metric="hashrate_ethash_mhs")["verdict"] == "implausibly_low"
   and gb.classify("RTX 4090", 25, metric="hashrate_ethash_mhs")["fraud"] is False)
ok("hashrate metric maps common mining algos (daggerhashimoto/ethash/etchash)",
   gb.HASHRATE_ALGO_METRIC.get("daggerhashimoto") == "hashrate_ethash_mhs"
   and gb.HASHRATE_ALGO_METRIC.get("etchash") == "hashrate_ethash_mhs")

# ---------------------------------------------------------------- unknowns never flag
ok("a model absent from a metric's table is unknown_model (recorded, not flagged)",
   gb.classify("A100", 500, metric="blender_optix")["verdict"] == "unknown_model")
ok("an unknown metric is unknown_metric", gb.classify("H100", 700, metric="nope")["verdict"] == "unknown_metric")
ok("a missing/zero score is no_score", gb.classify("H100", 0)["verdict"] == "no_score")
ok("a non-numeric score is handled gracefully", gb.classify("H100", "x")["verdict"] == "no_score")

# ---------------------------------------------------------------- classify_all aggregate (endpoint path)
# consistent FP16 + consistent Blender -> overall consistent
agg = gb.classify_all("RTX 4090", {"tflops_fp16": 260, "blender_optix": 12000, "task_id": 7})
ok("classify_all grades every recognised metric in the (signed) proof", len(agg["results"]) == 2)
ok("all-consistent -> aggregate 'consistent', no fraud", agg["verdict"] == "consistent" and not agg["fraud"])

# a FP16 gross over-claim on an H100 listing -> aggregate implausibly_low AND fraud
aggf = gb.classify_all("H100", {"tflops_fp16": 40})
ok("a freezing-metric over-claim -> aggregate fraud=True", aggf["verdict"] == "implausibly_low" and aggf["fraud"] is True)

# Blender-only over-claim -> flagged (implausibly_low) but NOT fraud (advisory metric)
aggb = gb.classify_all("RTX 4090", {"blender_optix": 1500})
ok("an advisory-only over-claim flags (implausibly_low) but never freezes",
   aggb["verdict"] == "implausibly_low" and aggb["fraud"] is False)

# no recognised metrics -> no verdict, no freeze
ok("a proof with no benchmark scores yields no verdict",
   gb.classify_all("H100", {"task_id": 1, "ts": 2})["verdict"] is None)

# ---------------------------------------------------------------- fraud floor is env-tunable (FP16)
import os   # noqa: E402
os.environ["GPU_BENCH_FRAUD_FLOOR_FRAC"] = "0.40"
ok("raising the fraud floor catches a borderline FP16 over-claim",
   gb.classify("H100", 250, metric="tflops_fp16")["fraud"] is True)
os.environ.pop("GPU_BENCH_FRAUD_FLOOR_FRAC", None)

print(f"\n=== gpu_benchmark: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
