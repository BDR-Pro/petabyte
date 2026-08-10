#!/usr/bin/env python3
"""validate_dashboards.py — guard that provisioned dashboards only query metrics that exist.

Builds the authoritative metric allowlist from the SOURCE OF TRUTH:
  * lumaris_api/observability.py  init_metrics()  (C/G/H definitions, + _total/_bucket/_count/_sum)
  * lumaris_api/main.py           _marketplace_metrics scrape-time gauges ("name": "petabyte_...")
  * observability/prometheus/rules/petabyte_rules.yaml  recording rules (record: petabyte:...)
  * a small, explicit set of standard exporter metrics declared in prometheus.yml
Then it parses every PromQL target in every dashboard and fails if a referenced metric is not in
the allowlist. Also validates JSON, unique dashboard UIDs, and that datasource UIDs are known.

Run: python observability/grafana/validate_dashboards.py
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = os.path.join(ROOT, "lumaris_api")
DASH = os.path.join(ROOT, "observability", "grafana", "dashboards")

# --- Standard exporter metrics we deliberately allow (declared in prometheus.yml scrape jobs) ---
EXPORTER = {
    "up", "pg_up", "pg_stat_activity_count", "pg_settings_max_connections", "redis_up",
    "node_filesystem_avail_bytes", "node_filesystem_size_bytes",
    "node_memory_MemAvailable_bytes", "node_memory_MemTotal_bytes", "node_load1",
    "prometheus_tsdb_head_max_time_seconds",
    "DCGM_FI_DEV_GPU_UTIL", "DCGM_FI_DEV_FB_USED", "DCGM_FI_DEV_FB_FREE",
    "DCGM_FI_DEV_GPU_TEMP", "DCGM_FI_DEV_XID_ERRORS", "DCGM_FI_DEV_POWER_USAGE",
}

PROMQL_KEYWORDS = {
    "sum", "rate", "irate", "increase", "avg", "min", "max", "count", "count_values",
    "histogram_quantile", "clamp_min", "clamp_max", "topk", "bottomk", "quantile",
    "by", "on", "without", "ignoring", "group_left", "group_right", "and", "or", "unless",
    "bool", "offset", "time", "vector", "scalar", "absent", "absent_over_time", "delta",
    "idelta", "deriv", "predict_linear", "stddev", "stdvar", "avg_over_time", "sum_over_time",
    "max_over_time", "min_over_time", "count_over_time", "last_over_time", "le", "inf", "nan",
    "label_replace", "label_join", "round", "ceil", "floor", "abs", "e",
}


def build_allowlist():
    allow = set(EXPORTER)
    # app metrics from init_metrics(): C("name",..), G(...), H(...)
    obs = open(os.path.join(API, "observability.py")).read()
    for m in re.finditer(r'\b([CGH])\(\s*"(petabyte_[a-z0-9_]+)"', obs):
        kind, name = m.group(1), m.group(2)
        allow.add(name)
        if kind == "C":
            allow.add(name)                       # counters are already *_total
        if kind == "H":
            for suf in ("_bucket", "_count", "_sum"):
                allow.add(name + suf)
    # scrape-time gauges from _marketplace_metrics: {"name": "petabyte_..."}
    main = open(os.path.join(API, "main.py")).read()
    for m in re.finditer(r'"name":\s*"(petabyte_[a-z0-9_]+)"', main):
        allow.add(m.group(1))
    # recording rules: record: petabyte:...
    rules = open(os.path.join(ROOT, "observability", "prometheus", "rules",
                              "petabyte_rules.yaml")).read()
    for m in re.finditer(r'record:\s*(petabyte:[a-z0-9_:]+)', rules):
        allow.add(m.group(1))
    return allow


def metrics_in_expr(expr):
    e = re.sub(r"\{[^{}]*\}", " ", expr)               # drop label matchers
    e = re.sub(r"\[[^\]]*\]", " ", e)                  # drop ranges
    e = re.sub(r"\b(?:by|on|without|group_left|group_right|ignoring)\s*\([^()]*\)", " ", e)
    e = re.sub(r"\$__[A-Za-z_]+", " ", e)              # $__rate_interval etc.
    e = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*", " ", e)    # $environment etc.
    funcs = set(re.findall(r"([A-Za-z_:][A-Za-z0-9_:]*)\s*\(", e))
    out = set()
    for tok in re.findall(r"[A-Za-z_:][A-Za-z0-9_:]*", e):
        if tok in funcs or tok in PROMQL_KEYWORDS:
            continue
        if re.fullmatch(r"[0-9.]+", tok):
            continue
        out.add(tok)
    return out


def main():
    allow = build_allowlist()
    ds_uids = {"prometheus", "loki", "tempo"}
    fail = 0
    seen_uid = {}
    prom_metrics_checked = 0
    files = sorted(glob.glob(os.path.join(DASH, "*.json")))
    for f in files:
        name = os.path.basename(f)
        try:
            d = json.load(open(f))
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {name}: invalid JSON: {e}")
            fail += 1
            continue
        uid = d.get("uid")
        if not uid:
            print(f"FAIL  {name}: missing uid")
            fail += 1
        if uid in seen_uid:
            print(f"FAIL  {name}: duplicate uid '{uid}' (also {seen_uid[uid]})")
            fail += 1
        seen_uid[uid] = name
        unknown = set()
        for p in d.get("panels", []):
            for t in p.get("targets", []):
                ds = (t.get("datasource") or {}).get("uid")
                if ds and ds not in ds_uids:
                    print(f"FAIL  {name}: panel '{p.get('title')}' unknown datasource uid '{ds}'")
                    fail += 1
                expr = t.get("expr", "")
                if not expr:
                    continue
                # structural lint: balanced (), {}, []
                for op, cl in (("(", ")"), ("{", "}"), ("[", "]")):
                    if expr.count(op) != expr.count(cl):
                        print(f"FAIL  {name}: panel '{p.get('title')}' unbalanced '{op}{cl}': {expr[:80]}")
                        fail += 1
                if ds == "loki":
                    if "{" not in expr:               # every LogQL query needs a stream selector
                        print(f"FAIL  {name}: LogQL missing a stream selector: {expr[:80]}")
                        fail += 1
                    continue                          # metric-existence check is Prometheus-only
                prom_metrics_checked += 1
                for metric in metrics_in_expr(expr):
                    if metric in allow:
                        continue
                    if metric.startswith("DCGM_FI_DEV_"):
                        continue
                    unknown.add(metric)
        if unknown:
            fail += 1
            print(f"FAIL  {name}: references unknown metric(s): {sorted(unknown)}")
        else:
            npanels = len([p for p in d.get("panels", []) if p.get("type") != "row"])
            print(f"ok    {name:22} uid={uid:22} panels={npanels}")
    print(f"\nallowlist size={len(allow)}  prom targets checked={prom_metrics_checked}")
    print(f"=== validate_dashboards: {'0 failures' if fail == 0 else str(fail) + ' FAILED'} ===")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
