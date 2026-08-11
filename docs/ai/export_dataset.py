#!/usr/bin/env python3
"""Export the GPU-authenticity training dataset to JSONL for model training.

Run from the repo root with the SAME database the API uses:

    DATABASE_URL=…  SECRET_KEY=…  SERVER_PRIVATE_KEY=… \\
        python docs/ai/export_dataset.py --out dataset.jsonl

Writes one JSON object (feature row) per line to --out (default: stdout); prints headline
stats to stderr. GPU + performance signals only — no PII.
"""
import argparse
import json
import os
import sys

# Make lumaris_api importable (db.py, training_data.py live there).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "lumaris_api"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Export the GPU-authenticity dataset as JSONL.")
    ap.add_argument("--out", default="-", help="output file, or '-' for stdout (default)")
    ap.add_argument("--limit", type=int, default=0, help="max rows (0 = all)")
    ap.add_argument("--since-id", type=int, default=0, help="only samples with id > this")
    args = ap.parse_args()

    import db as dbmod           # noqa: E402 — after sys.path setup
    import training_data as td   # noqa: E402

    s = dbmod.SessionLocal()
    try:
        rows = td.export_authenticity_dataset(s, limit=(args.limit or None), since_id=args.since_id)
        stats = td.dataset_stats(s)
    finally:
        s.close()

    out = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8")
    try:
        for r in rows:
            out.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()

    sys.stderr.write(f"exported {len(rows)} samples -> "
                     f"{'stdout' if args.out == '-' else args.out}; "
                     f"stats={json.dumps(stats)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
