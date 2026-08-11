"""gpu_benchmark_test.py — the gamer-style GPU authenticity check.

Compare a measured FP16 matmul score to the PUBLIC reference band for the CLAIMED GPU
model and get an honest verdict: consistent / over-claim (fraud) / suspiciously-high /
unknown. Pure functions — no GPU, no network, no DB. Run: python gpu_benchmark_test.py
"""
import os

# lock the band fractions so the assertions are deterministic regardless of env.
os.environ["GPU_BENCH_LOW_FRAC"] = "0.30"
os.environ["GPU_BENCH_HIGH_FRAC"] = "1.15"
os.environ["GPU_BENCH_FRAUD_FLOOR_FRAC"] = "0.20"

import gpu_benchmark as gb   # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---------------------------------------------------------------- normalize_model
ok("normalize strips vendor prefix + memory suffix (H100)",
   gb.normalize_model("NVIDIA H100 80GB HBM3") == "H100")
ok("normalize handles A100-SXM4-80GB dash form", gb.normalize_model("NVIDIA A100-SXM4-80GB") == "A100")
ok("normalize does NOT confuse A10 with A100",
   gb.normalize_model("NVIDIA A10") == "A10" and gb.normalize_model("NVIDIA A100") == "A100")
ok("normalize GeForce RTX 4090", gb.normalize_model("GeForce RTX 4090") == "RTX 4090")
ok("normalize packed 'rtx4090'", gb.normalize_model("rtx4090") == "RTX 4090")
ok("normalize folds H100 board variants (PCIe/SXM) into H100", gb.normalize_model("H100 PCIe") == "H100")
ok("normalize unknown card -> None", gb.normalize_model("FooGPU 9000") is None)
ok("normalize empty -> None", gb.normalize_model("") is None and gb.normalize_model(None) is None)

# ---------------------------------------------------------------- reference_peak
_key, _peak = gb.reference_peak("nvidia h100")
ok("reference_peak resolves H100 to its published FP16 peak", _key == "H100" and _peak == 989.0)

# ---------------------------------------------------------------- classify: consistent
c = gb.classify("H100", 720, metric="tflops_fp16")   # ~73% of peak — a real H100 matmul
ok("a genuine H100 score (720 TFLOPS) is CONSISTENT", c["verdict"] == "consistent" and not c["fraud"])
ok("consistent verdict carries the resolved model + band", c["model"] == "H100" and c["band"][0] > 0)

c2 = gb.classify("RTX 4090", 180, metric="tflops_fp16")
ok("a genuine RTX 4090 score is CONSISTENT (not flagged)", c2["verdict"] == "consistent" and not c2["fraud"])

# ---------------------------------------------------------------- classify: over-claim = fraud
low = gb.classify("H100", 55, metric="tflops_fp16")   # T4-class number under an H100 listing
ok("claiming H100 but measuring T4-class TFLOPS -> implausibly_low", low["verdict"] == "implausibly_low")
ok("a GROSS H100 over-claim is flagged as FRAUD (freeze)", low["fraud"] is True)

# a mildly-low reading (throttled, small matmul) is flagged but NOT auto-frozen.
soft = gb.classify("H100", 250, metric="tflops_fp16")   # 25% of peak: below 30% floor, above 20% fraud floor
ok("a mildly-low H100 reading is implausibly_low but NOT fraud (protects honest sellers)",
   soft["verdict"] == "implausibly_low" and soft["fraud"] is False)

# ---------------------------------------------------------------- classify: suspiciously high
hi = gb.classify("T4", 400, metric="tflops_fp16")   # far above what a T4 can do
ok("a T4 that reports 400 TFLOPS is suspiciously_high (never a fraud freeze)",
   hi["verdict"] == "suspiciously_high" and hi["fraud"] is False)

# ---------------------------------------------------------------- classify: unknowns never freeze
unk = gb.classify("FooGPU 9000", 500, metric="tflops_fp16")
ok("an unknown model is unknown_model, never frozen", unk["verdict"] == "unknown_model" and not unk["fraud"])
ok("an unknown metric is unknown_metric, never frozen",
   gb.classify("H100", 700, metric="graphics_score")["verdict"] == "unknown_metric")
ok("a missing/zero score is no_score, never frozen",
   gb.classify("H100", 0)["verdict"] == "no_score" and gb.classify("H100", None)["verdict"] == "no_score")
ok("a non-numeric score is handled gracefully",
   gb.classify("H100", "not-a-number")["verdict"] == "no_score")

# ---------------------------------------------------------------- fraud floor is env-tunable
os.environ["GPU_BENCH_FRAUD_FLOOR_FRAC"] = "0.40"
strict = gb.classify("H100", 250, metric="tflops_fp16")   # 250 < 0.40*989 now
ok("raising the fraud floor catches a borderline over-claim", strict["fraud"] is True)
os.environ["GPU_BENCH_FRAUD_FLOOR_FRAC"] = "0.20"

print(f"\n=== gpu_benchmark: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
