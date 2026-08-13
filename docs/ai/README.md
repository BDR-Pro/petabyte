# AI datasets — where to get them

This folder is the entry point for Petabyte's machine-learning data. Today it holds the
**GPU-authenticity dataset** — the labelled corpus the marketplace accumulates from every
benchmark and idle-mining report, ready to train a fraud / authenticity classifier.
Background + design: [`../DATA_MOAT.md`](../DATA_MOAT.md).

**GPU + performance signals only — no PII.** Access is admin-scoped.

## Three ways to get the dataset

### 1. Live API (admin token)
```bash
# JSON (feature rows + headline stats)
curl -H "Authorization: Bearer $ADMIN_JWT" \
  "https://petabyte.market/admin/dataset/authenticity?limit=5000"

# JSONL, straight into a file for a trainer
curl -H "Authorization: Bearer $ADMIN_JWT" \
  "https://petabyte.market/admin/dataset/authenticity?format=jsonl&since_id=0" \
  > dataset.jsonl
```
`since_id` enables incremental pulls (pass the largest `sample_id` you've already ingested);
`limit` bounds the page.

### 2. Export script (direct from the database)
Run from the repo root with the **same `DATABASE_URL`** the API uses:
```bash
DATABASE_URL=postgresql+psycopg2://…  SECRET_KEY=…  SERVER_PRIVATE_KEY=… \
  python docs/ai/export_dataset.py --out dataset.jsonl
# writes one JSON object per line; prints stats to stderr
```

### 3. In code
```python
import training_data as td            # lumaris_api/training_data.py
rows  = td.export_authenticity_dataset(db, limit=None, since_id=0)
stats = td.dataset_stats(db)
```

## Row schema (features + labels)

Each row is one benchmark or idle-hashrate observation:

| Group | Fields |
|---|---|
| **id / claim** | `sample_id`, `spec_id`, `gpu_model`, `gpu_model_normalized`, `source` (`benchmark` \| `idle_mining`), `created_at` |
| **signals** | `metric_<name>` (raw score per metric: `tflops_fp16`, `blender_optix`, `cinebench_2024_gpu`, `pugetbench_*`, `hashrate_ethash_mhs`), `tokens_sec`, `elapsed_s`, `pow_verified` |
| **derived** | `ratio_<metric>` = score ÷ public reference for the claimed model (the model-invariant feature) |
| **context** | `reputation`, `jobs_completed`, `jobs_failed`, `fraud_count`, `attested`, `confidential`, `region_verified` |
| **labels** | `label_fraud` (bool), `label_verdict` (consistent / implausibly_low / suspiciously_high / …) |

## Status

This is a **collection + export** pipeline — the value is the accumulating, hard-to-replicate,
labelled corpus. Training a classifier on it (and feeding its score back into the trust ladder)
is the next step; the features and labels are already in the shape it needs.
