"""training_data.py — export the GPU-authenticity dataset for model training.

Petabyte accumulates a labelled corpus of GPU performance signals (BenchmarkSample): for every
benchmark and idle-mining report we record the scores by metric, the server-timing, the
proof-of-work result, the spec's context (reputation, job history, attestation), and — over
time — the fraud outcome. That is exactly the (features, label) shape a fraud / authenticity
classifier trains on, and it compounds: every real benchmark makes the model better. This module
turns the raw log into feature rows (score + ratio-to-public-reference per metric) plus a label.

GPU + performance signals only — no PII. Access is admin-scoped (see main.py).
"""
from __future__ import annotations

import json
from collections import Counter

# The benchmark metrics whose per-model public reference we can turn into a `ratio_*` feature.
from gpu_benchmark import normalize_model, reference_value, KNOWN_METRICS


def _row_features(s) -> dict:
    try:
        metrics = json.loads(s.metrics or "{}")
    except Exception:
        metrics = {}
    feat = {
        "sample_id": s.id,
        "spec_id": s.spec_id,
        "gpu_model": s.gpu_model,
        "gpu_model_normalized": normalize_model(s.gpu_model or ""),
        "source": s.source,
        "verdict": s.verdict,
        "pow_verified": s.pow_verified,
        "elapsed_s": s.elapsed_s,
        "tokens_sec": s.tokens_sec,
        "reputation": s.reputation,
        "jobs_completed": s.jobs_completed,
        "jobs_failed": s.jobs_failed,
        "fraud_count": s.fraud_count,
        "attested": s.attested,
        "confidential": s.confidential,
        "region_verified": s.region_verified,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        # supervised LABELS
        "label_fraud": bool((s.fraud_count or 0) > 0),
        "label_verdict": s.verdict,
    }
    # per-metric features: the raw score, and its ratio to the public reference for the CLAIMED
    # model — the ratio is the model-invariant signal a classifier actually learns from.
    for m, score in metrics.items():
        if m not in KNOWN_METRICS:
            continue
        feat[f"metric_{m}"] = score
        _key, ref = reference_value(s.gpu_model or "", m)
        if ref:
            try:
                feat[f"ratio_{m}"] = round(float(score) / ref, 4)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    return feat


def export_authenticity_dataset(db, limit: int = None, since_id: int = 0) -> list:
    """Feature rows (newest first) for the GPU-authenticity model. `since_id` supports
    incremental pulls; `limit` bounds the page."""
    from db import BenchmarkSample
    q = (db.query(BenchmarkSample)
         .filter(BenchmarkSample.id > int(since_id or 0))
         .order_by(BenchmarkSample.id.desc()))
    if limit:
        q = q.limit(int(limit))
    return [_row_features(s) for s in q.all()]


def dataset_stats(db) -> dict:
    """Headline numbers for the dataset (the data-moat scoreboard)."""
    from db import BenchmarkSample
    rows = db.query(BenchmarkSample).all()
    verdicts = Counter(r.verdict for r in rows if r.verdict)
    sources = Counter(r.source for r in rows if r.source)
    models = {normalize_model(r.gpu_model or "") for r in rows}
    models.discard(None)
    return {
        "samples": len(rows),
        "fraud_positive_samples": sum(1 for r in rows if (r.fraud_count or 0) > 0),
        "pow_verified_samples": sum(1 for r in rows if r.pow_verified is True),
        "distinct_gpu_models": len(models),
        "by_verdict": dict(verdicts),
        "by_source": dict(sources),
    }


def to_jsonl(rows: list) -> str:
    """Newline-delimited JSON — the format most training pipelines ingest directly."""
    return "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows)
