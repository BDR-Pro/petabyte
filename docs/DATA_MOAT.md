# Data moat — the GPU-authenticity training dataset

Every benchmark and idle-mining report Petabyte processes is also a **labelled data point**. As
the marketplace runs, it accumulates a proprietary corpus that pairs GPU performance signals with
outcomes — exactly the shape a fraud / authenticity model trains on. The dataset compounds: more
real jobs → more labelled samples → a sharper model → harder-to-fake listings. Competitors can
copy the *checks*; they can't copy the *data*.

**No PII.** The corpus is GPU + performance signals only (models, scores, timings, attestation
state, job history). No user identity, no workload contents. Export is admin-scoped.

## What is collected

Each row of `benchmark_samples` (append-only) is written on every benchmark submission and every
idle-mining hashrate report (`db.record_benchmark_sample`):

| Group | Fields |
|---|---|
| **Signals** | `metrics` (score per metric: `tflops_fp16`, `blender_optix`, `cinebench_2024_gpu`, `pugetbench_*`, `hashrate_ethash_mhs`), `tokens_sec`, `elapsed_s` (server-observed), `pow_verified` (fresh proof-of-work answered) |
| **Claim** | `gpu_model` (what the seller listed) |
| **Context** | `reputation`, `jobs_completed`, `jobs_failed`, `attested`, `confidential`, `region_verified` |
| **Label** | `verdict` (consistent / implausibly_low / suspiciously_high) and, over time, `fraud_count` (the ground-truth fraud outcome) |

## Feature engineering (built into the export)

`training_data.export_authenticity_dataset()` turns each raw sample into model-ready features:

- **`ratio_<metric>`** — the score divided by the *public reference* for the claimed GPU model.
  This ratio, not the raw score, is the model-invariant signal a classifier learns from (an
  honest card of any tier sits near 1.0; an over-claim sits well below).
- **`gpu_model_normalized`** — canonical model key (vendor prefixes / memory suffixes stripped).
- **Supervised labels** — `label_fraud` (did this seller get frozen?) and `label_verdict`.

Multiple metrics per card capture *independent* GPU dimensions — compute (TFLOPS), RT-core render
(Blender), and memory bandwidth (hashrate) — so the model can catch a card that fakes one dimension
but not another.

## Access

- `GET /admin/dataset/authenticity` (admin-only) — feature rows + headline stats (`?format=jsonl`
  for direct trainer ingestion, `?since_id=` for incremental pulls, `?limit=`).
- `training_data.dataset_stats(db)` — the data-moat scoreboard: sample count, fraud positives,
  proof-of-work-verified samples, distinct GPU models, breakdown by verdict / source.

## Honest note

Today this is a **collection + export** pipeline, not a trained model — the value is the
accumulating, hard-to-replicate, labelled dataset. Training a classifier on it (and, later,
feeding its score back into the trust ladder) is the natural next step; the features and labels are
already in the shape it needs. Tests: `training_data_test.py` (export shape, ratio features,
labels, incremental pulls, JSONL) + `smoke_test.py` (end-to-end collection + admin export).
