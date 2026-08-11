"""training_data_test.py — the GPU-authenticity training dataset is collected + exportable.

Offline, no network: record a few BenchmarkSample rows directly, then assert the export turns
them into feature rows (score + ratio-to-public-reference per metric) with supervised labels,
and that dataset_stats summarises them. GPU/perf signals only, no PII.

Run: python training_data_test.py
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./training_data_test.db"   # forced isolated SQLite
os.environ["SECRET_KEY"] = "t"
from cryptography.fernet import Fernet   # noqa: E402
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()

for _f in ("training_data_test.db", "training_data_test.db-wal", "training_data_test.db-shm"):
    if os.path.exists(_f):
        os.remove(_f)

import db as dbmod   # noqa: E402
dbmod.init_db()
import training_data as td   # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _seller_spec(db, name, gpu):
    u = dbmod.create_user(db, name, "hunter2-correct-horse")
    s = dbmod.SellerSpec(user_id=u.id, cpu=8, ram=16, price_per_hour=2.0, duration=24,
                         provider=name, gpu_model=gpu, attested=True, jobs_completed=10,
                         jobs_failed=1)
    db.add(s); db.commit(); db.refresh(s)
    return u, s


db = dbmod.SessionLocal()
uA, sA = _seller_spec(db, "trnA", "RTX 4090")
uB, sB = _seller_spec(db, "trnB", "H100")

# a consistent 4090 benchmark, a fraud-flagged over-claim, and an idle-mining hashrate report
dbmod.record_benchmark_sample(db, sA, source="benchmark",
                              metrics={"tflops_fp16": 300.0}, verdict="consistent",
                              pow_verified=True, elapsed_s=4.2, tokens_sec=1800.0)
sB.fraud_count = 1; db.add(sB); db.commit()
dbmod.record_benchmark_sample(db, sB, source="benchmark",
                              metrics={"tflops_fp16": 40.0}, verdict="implausibly_low",
                              pow_verified=True, elapsed_s=3.0)
dbmod.record_benchmark_sample(db, sA, source="idle_mining",
                              metrics={"hashrate_ethash_mhs": 120.0}, verdict="consistent")

# ---------------------------------------------------------------- export shape
rows = td.export_authenticity_dataset(db)
ok("every recorded sample becomes a feature row", len(rows) == 3)
_r = next(r for r in rows if r["source"] == "benchmark" and r["gpu_model"] == "RTX 4090")
ok("feature row carries the raw metric score", _r.get("metric_tflops_fp16") == 300.0)
ok("feature row carries the ratio-to-public-reference (300/330 for a 4090)",
   _r.get("ratio_tflops_fp16") == round(300.0 / 330.0, 4))
ok("feature row snapshots spec context (reputation / jobs / attestation)",
   _r["jobs_completed"] == 10 and _r["attested"] is True and "reputation" in _r)
ok("gpu_model is normalized for the model", _r["gpu_model_normalized"] == "RTX 4090")

# ---------------------------------------------------------------- labels
_fraud_row = next(r for r in rows if r["gpu_model"] == "H100")
ok("a fraud-flagged sample is labelled label_fraud=True", _fraud_row["label_fraud"] is True)
ok("a clean sample is labelled label_fraud=False", _r["label_fraud"] is False)
ok("the verdict is carried as a label", _r["label_verdict"] == "consistent")
_idle = next(r for r in rows if r["source"] == "idle_mining")
ok("an idle-mining hashrate sample gets its ratio feature too",
   _idle.get("ratio_hashrate_ethash_mhs") == round(120.0 / 130.0, 4))

# ---------------------------------------------------------------- incremental pull + stats
_after = td.export_authenticity_dataset(db, since_id=rows[0]["sample_id"])
ok("since_id enables incremental pulls (nothing newer than the newest)", _after == [])
_st = td.dataset_stats(db)
ok("dataset stats count all samples", _st["samples"] == 3)
ok("dataset stats count fraud positives + distinct models",
   _st["fraud_positive_samples"] == 1 and _st["distinct_gpu_models"] == 2)
ok("dataset stats break down by verdict + source",
   _st["by_verdict"].get("consistent") == 2 and _st["by_source"].get("idle_mining") == 1)

# ---------------------------------------------------------------- jsonl for trainers
_jsonl = td.to_jsonl(rows)
ok("jsonl export is newline-delimited JSON (one object per line)",
   len(_jsonl.splitlines()) == 3 and _jsonl.splitlines()[0].startswith("{"))

db.close()
print(f"\n=== training_data: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
