"""gpu_benchmark.py — is the reported benchmark consistent with the CLAIMED GPU model?

The idea (a seller's request): the way a gamer proves their card is real — run a
benchmark, get a score, compare it to the public numbers everyone knows for that
exact card. We do the same with a COMPUTE benchmark instead of a graphics one:

    (claimed GPU model, measured score)  ->  compare to published spec  ->  verdict

Why a compute benchmark and not 3DMark/Unigine: Petabyte's fleet mixes gaming rigs
with *headless* datacenter GPUs (H100/A100/L4) that have no display pipeline and
can't run a graphics benchmark at all. FP16 dense matrix-multiply throughput
(TFLOPS), on the other hand, every GPU can run, and it maps directly to the tensor
peak on the vendor datasheet — so one metric covers the whole fleet. (A gaming
score plugs into the exact same band framework; add a `graphics_score` band to a
model's entry and `classify(..., metric="graphics_score")` works unchanged.)

Honest boundaries — what this does and does NOT prove:
  * It checks a performance *class*, not the exact die. Adjacent tiers overlap, so
    it reliably catches GROSS over-claims (list an H100, actually run a T4 / a
    consumer mid-range card) — not an A100-for-H100 swap.
  * It catches OVER-claiming (claiming a *stronger* card than the silicon can do).
    It does not, on its own, stop bait-and-switch (benchmark a real H100, then run
    the paid job on something weaker) — that needs the benchmark to be a
    platform-dispatched, seed-bound, server-timed measurement re-run against real
    jobs. This module is the reference-comparison half of that.
  * The score is only as trustworthy as the harness that produced it. A real
    server-timed measurement makes this strong; a self-reported number makes it a
    consistency hint. The agent measures FP16 matmul TFLOPS on-device
    (`task_fetcher._measure_fp16_tflops`); the platform records the signed claim and
    checks it here.

Reference numbers below are published **dense FP16 tensor-core peak TFLOPS** from
vendor datasheets (FP16 accumulate; the sparsity-doubled figure is NOT used). A
genuine device running a decent matmul reaches a large fraction of peak; a much
weaker card physically cannot. Bands are deliberately wide so an honestly throttled
or small-matmul run is never flagged — we only fire fraud on a gross shortfall.

No network, no GPU, pure functions — fully testable offline.
"""
import os
import re

# canonical model -> published dense FP16 tensor-core peak TFLOPS (vendor datasheets).
# Wide by design; see module docstring. Extend freely — unknown models never freeze.
_PEAK_TFLOPS_FP16 = {
    # ---- NVIDIA datacenter (Hopper / Ampere / Ada / Volta / Turing) ----
    "H200": 989.0,
    "H100": 989.0,          # SXM peak; board variant (PCIe ~756) folds in — bands are wide
    "A100": 312.0,          # 40GB & 80GB, SXM/PCIe share the tensor peak
    "L40S": 366.0,
    "L40": 181.0,
    "L4": 121.0,
    "A40": 150.0,
    "A30": 165.0,
    "A10G": 125.0,
    "A10": 125.0,
    "V100": 125.0,
    "T4": 65.0,
    "P100": 21.0,           # no tensor cores; raw FP16
    # ---- NVIDIA RTX / GeForce (consumer & workstation) ----
    "RTX 5090": 450.0,
    "RTX 4090": 330.0,
    "RTX 4080": 195.0,
    "RTX 4070 TI": 160.0,
    "RTX 4070": 117.0,
    "RTX 3090 TI": 160.0,
    "RTX 3090": 142.0,
    "RTX 3080": 119.0,
    "RTX 3070": 81.0,
    "RTX A6000": 155.0,
    "RTX A5000": 111.0,
    "RTX A4000": 76.0,
    # ---- AMD Instinct (CDNA) ----
    "MI300X": 1300.0,
    "MI250X": 383.0,
    "MI250": 362.0,
    "MI210": 181.0,
}

# space-stripped canonical keys, longest first, so "H100 PCIE" beats "H100" and
# "A100" beats "A10" on a substring match.
_KEYS_BY_LEN = sorted(_PEAK_TFLOPS_FP16, key=lambda k: len(k.replace(" ", "")), reverse=True)

# vendor/marketing noise words dropped before matching.
_NOISE = re.compile(
    r"\b(NVIDIA|GEFORCE|TESLA|QUADRO|AMD|RADEON|INSTINCT|GPU|GRAPHICS|CARD|"
    r"SXM\d?|PCIE|PCIE\d?|HBM\d?E?|GDDR\d?X?)\b")


def _canon_text(raw: str) -> str:
    """Upper-case, strip punctuation & vendor noise, collapse whitespace."""
    s = (raw or "").upper()
    s = s.replace("®", " ").replace("(R)", " ").replace("™", " ").replace("(TM)", " ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)          # dashes/slashes -> spaces (A100-SXM4-80GB)
    s = _NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_model(raw: str):
    """Map a free-text GPU name to a canonical reference key, or None if unknown.

    Handles vendor prefixes, memory/board suffixes, and spacing:
      'NVIDIA H100 80GB HBM3'      -> 'H100'
      'NVIDIA A100-SXM4-80GB'      -> 'A100'
      'GeForce RTX 4090'           -> 'RTX 4090'
      'rtx4090'                    -> 'RTX 4090'
    """
    if not raw:
        return None
    packed = _canon_text(raw).replace(" ", "")
    if not packed:
        return None
    for key in _KEYS_BY_LEN:                      # longest-first substring match
        if key.replace(" ", "") in packed:
            return key
    return None


def reference_peak(gpu_model: str):
    """Published dense FP16 tensor peak TFLOPS for a claimed model, or None."""
    key = normalize_model(gpu_model)
    return (key, _PEAK_TFLOPS_FP16[key]) if key else (None, None)


# --- band fractions (env-tunable). Wide, to protect honest sellers. ---
def _f(env, default):
    try:
        return float(os.getenv(env, default))
    except (TypeError, ValueError):
        return float(default)


def _low_frac():   return _f("GPU_BENCH_LOW_FRAC", 0.30)     # consistent floor: 30% of peak
def _high_frac():  return _f("GPU_BENCH_HIGH_FRAC", 1.15)    # can't exceed peak by much
def _fraud_frac(): return _f("GPU_BENCH_FRAUD_FLOOR_FRAC", 0.20)  # below this = fraud


def classify(gpu_model: str, score, metric: str = "tflops_fp16") -> dict:
    """Compare a measured score to the claimed GPU model's public reference band.

    Returns a dict:
      verdict            one of consistent | implausibly_low | suspiciously_high |
                         unknown_model | unknown_metric | no_score
      fraud              True only on a GROSS over-claim (score below the fraud floor
                         of the claimed model) — the caller should freeze payouts.
      model / peak       resolved canonical model + its published peak TFLOPS
      score / ratio      the measured score and score/peak
      band               (low, high) plausible range for a genuine device
      detail             one-line human explanation
    """
    out = {"verdict": "unknown_model", "fraud": False, "metric": metric,
           "model": None, "peak": None, "score": None, "ratio": None,
           "band": None, "detail": ""}

    if metric != "tflops_fp16":
        # Only FP16 matmul TFLOPS has a reference table today. A gaming/graphics
        # score would resolve here once a band is added for it.
        out["verdict"] = "unknown_metric"
        out["detail"] = f"No public reference band for metric '{metric}'."
        return out

    try:
        score = float(score)
    except (TypeError, ValueError):
        score = None
    if score is None or score <= 0:
        out["verdict"] = "no_score"
        out["detail"] = "No usable benchmark score supplied."
        return out
    out["score"] = score

    key, peak = reference_peak(gpu_model)
    if not key:
        out["detail"] = f"'{gpu_model}' is not in the public reference table; cannot judge."
        return out

    low, high = round(peak * _low_frac(), 1), round(peak * _high_frac(), 1)
    fraud_floor = peak * _fraud_frac()
    ratio = round(score / peak, 3)
    out.update(model=key, peak=peak, ratio=ratio, band=(low, high))

    if score > high:
        out["verdict"] = "suspiciously_high"
        out["detail"] = (f"{score:.0f} TFLOPS exceeds the {key} published peak "
                         f"({peak:.0f}); the claimed model is weaker than the silicon "
                         f"measured, or the number is inflated.")
        return out
    if score < low:
        out["fraud"] = score < fraud_floor
        out["verdict"] = "implausibly_low"
        floor_txt = f" below the {int(_fraud_frac()*100)}%-of-peak fraud floor" if out["fraud"] else ""
        out["detail"] = (f"{score:.0f} TFLOPS is far below the {key} plausible floor "
                         f"({low:.0f}){floor_txt}; the claimed model is stronger than the "
                         f"silicon can deliver (over-claim).")
        return out

    out["verdict"] = "consistent"
    out["detail"] = (f"{score:.0f} TFLOPS is within the {key} plausible band "
                     f"({low:.0f}–{high:.0f}); consistent with the claimed model.")
    return out
