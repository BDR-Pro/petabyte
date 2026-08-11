"""gpu_benchmark.py — is a reported benchmark consistent with the CLAIMED GPU model?

The idea (a seller's request): the way a gamer proves a card is real — run a benchmark,
compare the score to the numbers everyone publicly knows for that exact card. We do the
same, across SEVERAL public benchmarks, and pick ones that are also **workload-relevant**
for Petabyte's fleet:

    (claimed GPU model, {metric: score, ...})  ->  compare each to public data  ->  verdict

Metrics wired today, each with a per-GPU public reference table:

  metric               what it is                              public reference        freezes?
  ─────────────────────────────────────────────────────────────────────────────────────────────
  tflops_fp16          FP16 dense matmul TFLOPS (measured)     vendor datasheet peak   YES
  blender_optix        Blender Open Data score (OptiX, sum of  opendata.blender.org    no (advisory)
                       standard-scene samples/min)             (median per GPU)
  cinebench_2024_gpu   Cinebench 2024 GPU (Redshift) score     Maxon Cinebench          no (advisory)
  pugetbench_resolve   PugetBench for DaVinci Resolve Studio   pugetsystems.com         no (advisory)
  pugetbench_premiere  PugetBench for Premiere Pro             pugetsystems.com         no (advisory)

Why these: **Blender is what Petabyte actually renders** (the agent shells out to a Blender
container), so a Blender benchmark measures the real workload and has abundant public data;
Cinebench covers Cinema 4D / Redshift users; PugetBench covers the video-editing fleet
(Resolve/Premiere). FP16 TFLOPS stays the one hardware-invariant, so it is the only metric
allowed to FREEZE payouts on a gross over-claim. The render/video metrics are **advisory**:
they surface a buyer-facing consistency signal and suppress a trust boost on a mismatch, but
never auto-freeze — their public medians depend on Blender/driver version, scene, and (for
Puget) the whole system, so they are corroboration, not proof.

Reference numbers are approximate public **medians** with deliberately wide tolerance, so an
honestly-throttled or slightly-different-version run is never flagged; a card absent from a
metric's table resolves to `unknown_model` (recorded, shown to buyers, never flagged).
Recalibrate against each source's live dataset — the tables are seeds, not gospel.

Honest boundaries (unchanged): this checks a performance *class*, not the exact die (adjacent
tiers overlap → catches gross over-claims, not an A100-for-H100 swap); it catches OVER-claiming,
not bait-and-switch; and a self-run score is only as trustworthy as the harness — the number is
node-signed (attributable) but becomes strong evidence only when platform-dispatched and
server-timed. NOTE render benchmarks rank GPUs DIFFERENTLY than TFLOPS (RT-core presence
dominates OptiX), which is exactly why each metric has its own table.

No network, no GPU, pure functions — fully testable offline.
"""
import os
import re

# ── per-metric reference tables ────────────────────────────────────────────────────────
# Each metric: higher-is-better reference value per canonical GPU model, band fractions
# (consistent floor / ceiling as a fraction of the reference; fraud floor used only when
# freezes=True), a public source citation, and whether it may freeze payouts.
_METRICS = {
    "tflops_fp16": {
        "label": "FP16 matmul TFLOPS", "unit": "TFLOPS", "freezes": True,
        "source": "vendor datasheet — dense FP16 tensor-core peak",
        "low": 0.30, "high": 1.15, "fraud": 0.20,
        "ref": {
            # NVIDIA datacenter
            "H200": 989.0, "H100": 989.0, "A100": 312.0, "L40S": 366.0, "L40": 181.0,
            "L4": 121.0, "A40": 150.0, "A30": 165.0, "A10G": 125.0, "A10": 125.0,
            "V100": 125.0, "T4": 65.0, "P100": 21.0,
            # NVIDIA RTX / GeForce
            "RTX 5090": 450.0, "RTX 4090": 330.0, "RTX 4080": 195.0, "RTX 4070 TI": 160.0,
            "RTX 4070": 117.0, "RTX 3090 TI": 160.0, "RTX 3090": 142.0, "RTX 3080": 119.0,
            "RTX 3070": 81.0, "RTX A6000": 155.0, "RTX A5000": 111.0, "RTX A4000": 76.0,
            # AMD Instinct
            "MI300X": 1300.0, "MI250X": 383.0, "MI250": 362.0, "MI210": 181.0,
        },
    },
    "blender_optix": {
        "label": "Blender Open Data score (OptiX)", "unit": "score", "freezes": False,
        "source": "opendata.blender.org — median samples/min, Blender 4.x OptiX (sum of scenes)",
        "low": 0.35, "high": 1.35, "fraud": 0.25,
        # RT-core cards where the public Blender data is solid. Datacenter cards without
        # consumer RT throughput (A100/T4/P100) are intentionally omitted → unknown_model.
        "ref": {
            "RTX 4090": 12500.0, "RTX 4080": 8800.0, "RTX 4070 TI": 7000.0, "RTX 4070": 5400.0,
            "RTX 3090 TI": 7200.0, "RTX 3090": 6300.0, "RTX 3080": 5400.0, "RTX 3070": 4300.0,
            "RTX A6000": 6200.0, "RTX A5000": 4800.0, "L40S": 10500.0, "L40": 8000.0,
            "A10": 3200.0, "L4": 3000.0,
        },
    },
    "cinebench_2024_gpu": {
        "label": "Cinebench 2024 GPU (Redshift)", "unit": "score", "freezes": False,
        "source": "Maxon Cinebench 2024 — GPU (Redshift) test",
        "low": 0.35, "high": 1.40, "fraud": 0.25,
        "ref": {  # approximate anchors for common cards
            "RTX 4090": 33000.0, "RTX 4080": 25000.0, "RTX 4070": 15000.0,
            "RTX 3090": 18000.0, "RTX 3080": 14000.0,
        },
    },
    "pugetbench_resolve": {
        "label": "PugetBench — DaVinci Resolve Studio", "unit": "score", "freezes": False,
        "source": "pugetsystems.com — PugetBench for DaVinci Resolve (overall)",
        "low": 0.30, "high": 1.50, "fraud": 0.25,  # widest: whole-system dependent
        "ref": {"RTX 4090": 12000.0, "RTX 4080": 10500.0, "RTX 3090": 8800.0},
    },
    "pugetbench_premiere": {
        "label": "PugetBench — Premiere Pro", "unit": "score", "freezes": False,
        "source": "pugetsystems.com — PugetBench for Premiere Pro (GPU score)",
        "low": 0.30, "high": 1.50, "fraud": 0.25,
        "ref": {"RTX 4090": 9500.0, "RTX 4080": 9000.0, "RTX 3090": 8000.0},
    },
}

KNOWN_METRICS = tuple(_METRICS)

# space-stripped canonical keys, longest first, so "H100 PCIE" beats "H100" and
# "A100" beats "A10" on a substring match. Union of every metric's models.
_ALL_MODELS = set()
for _m in _METRICS.values():
    _ALL_MODELS |= set(_m["ref"])
_KEYS_BY_LEN = sorted(_ALL_MODELS, key=lambda k: len(k.replace(" ", "")), reverse=True)

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

      'NVIDIA H100 80GB HBM3'  -> 'H100'   ·  'NVIDIA A100-SXM4-80GB' -> 'A100'
      'GeForce RTX 4090'       -> 'RTX 4090'  ·  'rtx4090' -> 'RTX 4090'
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


def reference_value(gpu_model: str, metric: str = "tflops_fp16"):
    """Public reference value for a claimed model under a metric: (canonical_key, value)
    or (key_or_None, None) when the model isn't in that metric's table."""
    m = _METRICS.get(metric)
    if not m:
        return (None, None)
    key = normalize_model(gpu_model)
    if not key:
        return (None, None)
    return (key, m["ref"].get(key))


def reference_peak(gpu_model: str):
    """Back-compat: FP16 TFLOPS reference for a model, or (None, None)."""
    return reference_value(gpu_model, "tflops_fp16")


def metric_meta(metric: str) -> dict:
    """Public-facing description of a metric (label/source/freezes) for docs/UI."""
    m = _METRICS.get(metric)
    if not m:
        return {}
    return {"label": m["label"], "source": m["source"], "freezes": m["freezes"], "unit": m["unit"]}


# ── band fractions (env-tunable) ────────────────────────────────────────────────────────
_ENV = {"low": "GPU_BENCH_LOW_FRAC", "high": "GPU_BENCH_HIGH_FRAC", "fraud": "GPU_BENCH_FRAUD_FLOOR_FRAC"}


def _frac(metric: str, kind: str) -> float:
    """A global GPU_BENCH_* override (kept for back-compat) wins; else the per-metric default."""
    v = os.getenv(_ENV[kind])
    if v is not None:
        try:
            return float(v)
        except ValueError:
            pass
    return float(_METRICS[metric][kind])


def classify(gpu_model: str, score, metric: str = "tflops_fp16") -> dict:
    """Compare one measured score to the claimed GPU model's public reference band.

    Returns a dict: verdict (consistent | implausibly_low | suspiciously_high |
    unknown_model | unknown_metric | no_score), fraud (True only when a FREEZING metric
    falls below its fraud floor), plus model/peak/score/ratio/band/detail and the metric's
    label/source/freezes for display.
    """
    m = _METRICS.get(metric)
    out = {"verdict": "unknown_metric", "fraud": False, "metric": metric,
           "label": m["label"] if m else metric, "source": m["source"] if m else None,
           "freezes": bool(m["freezes"]) if m else False,
           "model": None, "peak": None, "reference": None, "score": None,
           "ratio": None, "band": None, "detail": ""}
    if not m:
        out["detail"] = f"No public reference table for metric '{metric}'."
        return out

    unit = m["unit"]
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = None
    if score is None or score <= 0:
        out["verdict"] = "no_score"
        out["detail"] = "No usable benchmark score supplied."
        return out
    out["score"] = score

    key, ref = reference_value(gpu_model, metric)
    if not key or ref is None:
        out["verdict"] = "unknown_model"
        out["model"] = key
        out["detail"] = (f"'{gpu_model}' has no public {m['label']} reference; cannot judge "
                         f"(recorded, not flagged).")
        return out

    low, high = round(ref * _frac(metric, "low"), 1), round(ref * _frac(metric, "high"), 1)
    ratio = round(score / ref, 3)
    out.update(model=key, peak=ref, reference=ref, ratio=ratio, band=(low, high))

    if score > high:
        out["verdict"] = "suspiciously_high"
        out["detail"] = (f"{score:.0f} {unit} exceeds the {key} public {m['label']} "
                         f"({ref:.0f}); the claimed model is weaker than the silicon measured, "
                         f"or the number is inflated.")
        return out
    if score < low:
        out["fraud"] = bool(m["freezes"]) and score < ref * _frac(metric, "fraud")
        out["verdict"] = "implausibly_low"
        tail = " (below the fraud floor)" if out["fraud"] else ""
        out["detail"] = (f"{score:.0f} {unit} is far below the {key} plausible floor "
                         f"({low:.0f}) for {m['label']}{tail}; the claimed model is stronger "
                         f"than the silicon can deliver (over-claim).")
        return out

    out["verdict"] = "consistent"
    out["detail"] = (f"{score:.0f} {unit} is within the {key} plausible band "
                     f"({low:.0f}–{high:.0f}) for {m['label']}; consistent with the claimed model.")
    return out


def classify_all(gpu_model: str, source: dict) -> dict:
    """Classify every recognized benchmark metric present in `source` (a signed proof or
    meta dict) against the claimed model.

    Returns {verdict, fraud, results}: `results` is the per-metric list; `verdict` is the
    trust-relevant summary (over-claim beats high beats consistent); `fraud` is True only if
    a FREEZING metric is a gross over-claim (the caller should freeze payouts).
    """
    results = []
    if isinstance(source, dict):
        for metric in _METRICS:                      # stable order: tflops first
            if source.get(metric) is not None:
                results.append(classify(gpu_model, source.get(metric), metric=metric))

    graded = [r["verdict"] for r in results
              if r["verdict"] in ("consistent", "implausibly_low", "suspiciously_high")]
    fraud = any(r.get("fraud") for r in results)
    if fraud or "implausibly_low" in graded:
        verdict = "implausibly_low"
    elif "suspiciously_high" in graded:
        verdict = "suspiciously_high"
    elif "consistent" in graded:
        verdict = "consistent"
    else:
        verdict = None
    return {"verdict": verdict, "fraud": fraud, "results": results}
