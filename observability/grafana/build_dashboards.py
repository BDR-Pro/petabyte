#!/usr/bin/env python3
"""build_dashboards.py — generate Petabyte's provisioned Grafana dashboards.

Why a generator: it guarantees every panel is valid, consistently laid out, and — crucially —
references ONLY metrics that the platform actually emits (see the AUDITED SOURCES below). The
emitted JSON is committed to git and mounted read-only into Grafana, so `docker compose up -d`
loads it with no manual clicking. Re-run this after changing a panel: `python build_dashboards.py`.

AUDITED SOURCES (do not use a metric that is not here):
  * lumaris_api/observability.py  -> petabyte_* app metrics (bounded labels only)
  * lumaris_api/main.py _marketplace_metrics -> scrape-time petabyte_* gauges
  * observability/prometheus/rules/petabyte_rules.yaml -> petabyte:* recording rules
  * exporters declared in prometheus.yml: postgres_exporter (pg_*), redis_exporter (redis_*),
    node_exporter (node_*), NVIDIA DCGM (DCGM_FI_DEV_*), Prometheus (up, prometheus_*)
  * Loki: structured JSON logs, labels {service, environment}; body parsed with `| json`,
    event_name from lumaris_api/observability.py EVENTS + lumaris_agent/agent_telemetry.py.

TEST/LIVE safety: payment_mode is a SINGLE-SELECT variable, and every money panel filters
{payment_mode="$payment_mode"}. A panel can therefore only ever show one mode at a time — it is
structurally impossible for a LIVE panel to sum TEST money.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dashboards")

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

RED, AMBER, GREEN = "red", "orange", "green"


# --------------------------------------------------------------------------- ids + layout
class Ctx:
    def __init__(self):
        self.id = 0
        self.x = 0
        self.y = 0
        self.rowh = 0

    def nid(self):
        self.id += 1
        return self.id

    def place(self, w, h):
        if self.x + w > 24:
            self.y += self.rowh
            self.x = 0
            self.rowh = 0
        pos = {"h": h, "w": w, "x": self.x, "y": self.y}
        self.x += w
        self.rowh = max(self.rowh, h)
        return pos

    def newline(self):
        self.y += self.rowh
        self.x = 0
        self.rowh = 0


# --------------------------------------------------------------------------- targets
def T(expr, legend="", instant=False, exemplar=False, ds=PROM, refid="A"):
    t = {"datasource": ds, "editorMode": "code", "expr": expr,
         "legendFormat": legend, "range": not instant, "instant": instant, "refId": refid}
    if exemplar:
        t["exemplar"] = True
    return t


def LT(expr, refid="A"):
    return {"datasource": LOKI, "editorMode": "code", "expr": expr,
            "queryType": "range", "refId": refid}


def targets(specs, ds=PROM):
    out = []
    for i, sp in enumerate(specs):
        rid = chr(ord("A") + i)
        if isinstance(sp, tuple):
            expr, legend = sp[0], (sp[1] if len(sp) > 1 else "")
            out.append(T(expr, legend, ds=ds, refid=rid))
        else:
            sp = dict(sp)
            sp["refId"] = rid
            out.append(sp)
    return out


def thresholds(steps):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


# --------------------------------------------------------------------------- panels
def stat(ctx, title, tgts, unit="short", steps=None, w=4, h=4, desc="", color="value", ds=PROM):
    fc = {"defaults": {"unit": unit, "color": {"mode": "thresholds" if steps else "palette-classic"},
                       "thresholds": thresholds(steps or [(GREEN, None)])}, "overrides": []}
    return {"id": ctx.nid(), "type": "stat", "title": title, "description": desc,
            "datasource": ds, "gridPos": ctx.place(w, h),
            "targets": targets(tgts, ds=ds), "fieldConfig": fc,
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "orientation": "auto", "textMode": "auto", "colorMode": color,
                        "graphMode": "area", "justifyMode": "auto"}}


def gauge(ctx, title, tgts, unit="percent", steps=None, w=4, h=6, desc="", mx=100):
    fc = {"defaults": {"unit": unit, "min": 0, "max": mx,
                       "color": {"mode": "thresholds"},
                       "thresholds": thresholds(steps or [(GREEN, None)])}, "overrides": []}
    return {"id": ctx.nid(), "type": "gauge", "title": title, "description": desc,
            "datasource": PROM, "gridPos": ctx.place(w, h), "targets": targets(tgts),
            "fieldConfig": fc,
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "showThresholdLabels": False, "showThresholdMarkers": True}}


def ts(ctx, title, tgts, unit="short", steps=None, w=12, h=8, desc="", stack=False,
       exemplar=False, fill=10):
    custom = {"drawStyle": "line", "lineInterpolation": "smooth", "fillOpacity": fill,
              "showPoints": "never", "spanNulls": True}
    if stack:
        custom["stacking"] = {"mode": "normal", "group": "A"}
    fc = {"defaults": {"unit": unit, "custom": custom,
                       "color": {"mode": "palette-classic"},
                       "thresholds": thresholds(steps or [(GREEN, None)])}, "overrides": []}
    for t in tgts if isinstance(tgts, list) else []:
        pass
    tg = targets(tgts)
    if exemplar:
        for t in tg:
            t["exemplar"] = True
    return {"id": ctx.nid(), "type": "timeseries", "title": title, "description": desc,
            "datasource": PROM, "gridPos": ctx.place(w, h), "targets": tg, "fieldConfig": fc,
            "options": {"legend": {"displayMode": "list", "placement": "bottom",
                                   "calcs": ["lastNotNull", "max"]},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def barchart(ctx, title, expr, legend, unit="short", w=8, h=8, desc=""):
    fc = {"defaults": {"unit": unit, "color": {"mode": "palette-classic"},
                       "custom": {"fillOpacity": 80}, "thresholds": thresholds([(GREEN, None)])},
          "overrides": []}
    return {"id": ctx.nid(), "type": "barchart", "title": title, "description": desc,
            "datasource": PROM, "gridPos": ctx.place(w, h),
            "targets": [T(expr, legend, instant=True)], "fieldConfig": fc,
            "options": {"orientation": "horizontal", "showValue": "auto",
                        "legend": {"displayMode": "list", "placement": "bottom"}}}


def table(ctx, title, tgts, w=12, h=8, desc="", unit="short"):
    return {"id": ctx.nid(), "type": "table", "title": title, "description": desc,
            "datasource": PROM, "gridPos": ctx.place(w, h),
            "targets": [dict(t, format="table", instant=True) for t in targets(tgts)],
            "fieldConfig": {"defaults": {"unit": unit, "custom": {"align": "auto"}},
                            "overrides": []},
            "options": {"showHeader": True, "cellHeight": "sm",
                        "footer": {"show": False}},
            "transformations": [{"id": "merge", "options": {}}]}


def logs(ctx, title, expr, w=24, h=9, desc=""):
    return {"id": ctx.nid(), "type": "logs", "title": title, "description": desc,
            "datasource": LOKI, "gridPos": ctx.place(w, h), "targets": [LT(expr)],
            "options": {"showTime": True, "wrapLogMessage": True, "prettifyLogMessage": True,
                        "enableLogDetails": True, "dedupStrategy": "none",
                        "sortOrder": "Descending"}}


def text(ctx, title, md, w=24, h=3):
    return {"id": ctx.nid(), "type": "text", "title": title, "gridPos": ctx.place(w, h),
            "options": {"mode": "markdown", "content": md}}


def rowp(ctx, title):
    ctx.newline()
    p = {"id": ctx.nid(), "type": "row", "title": title, "collapsed": False,
         "gridPos": {"h": 1, "w": 24, "x": 0, "y": ctx.y}, "panels": []}
    ctx.y += 1
    return p


# --------------------------------------------------------------------------- variables
def qvar(name, label, metric, lbl, all_=False, multi=False, allvalue=None):
    v = {"name": name, "label": label, "type": "query", "datasource": PROM,
         "query": {"qryType": 1, "query": f"label_values({metric}, {lbl})",
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "definition": f"label_values({metric}, {lbl})", "refresh": 2, "sort": 1,
         "includeAll": all_, "multi": multi, "hide": 0, "current": {}, "options": []}
    if allvalue is not None:
        v["allValue"] = allvalue
    return v


def customvar(name, label, values, default):
    opts = [{"text": v, "value": v, "selected": v == default} for v in values]
    return {"name": name, "label": label, "type": "custom", "query": ",".join(values),
            "current": {"text": default, "value": default}, "options": opts,
            "includeAll": False, "multi": False, "hide": 0}


ENV = qvar("environment", "Environment", "petabyte_http_requests_total", "environment")
PAYMODE = customvar("payment_mode", "Payment mode (TEST/LIVE isolated)",
                    ["live", "test", "sandbox"], "live")
SERVICEVAR = {"name": "service", "label": "Service", "type": "custom",
              "query": "petabyte-api,petabyte-seller-agent",
              "current": {"text": "All", "value": "$__all"},
              "options": [], "includeAll": True, "allValue": "petabyte-.*",
              "multi": True, "hide": 0}
GPUMODEL = qvar("gpu_model", "GPU model (DCGM)", "DCGM_FI_DEV_GPU_TEMP", "modelName",
                all_=True, multi=True, allvalue=".*")


def dashboard(uid, title, tags, tvars, panels, refresh="30s"):
    return {"uid": uid, "title": title, "tags": tags, "schemaVersion": 39, "version": 1,
            "editable": True, "graphTooltip": 1, "liveNow": False, "refresh": refresh,
            "time": {"from": "now-6h", "to": "now"}, "timezone": "", "weekStart": "",
            "fiscalYearStartMonth": 0, "annotations": {"list": []}, "links": [],
            "templating": {"list": tvars},
            "timepicker": {}, "panels": panels}


# =========================================================================== dashboards
def d_executive():
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    M = 'payment_mode="$payment_mode",environment="$environment"'
    p.append(rowp(c, "Live marketplace"))
    p.append(stat(c, "Online GPUs", [(f"sum(petabyte_gpus_online{{{E}}})", "GPUs")],
                  steps=[(RED, None), (AMBER, 1), (GREEN, 5)], desc="Currently online GPU units."))
    p.append(stat(c, "Available GPUs", [(f"sum(petabyte_gpus_available{{{E}}})", "free")],
                  steps=[(RED, None), (GREEN, 1)]))
    p.append(stat(c, "Jobs running", [(f"sum(petabyte_jobs_running{{{E}}})", "running")]))
    p.append(stat(c, "Jobs completed (24h)",
                  [(f'sum(increase(petabyte_jobs_total{{job_status=~"completed|validated",{E}}}[24h]))',
                    "done")]))
    p.append(stat(c, "Job failure rate",
                  [(f'100 * sum(rate(petabyte_jobs_total{{job_status=~"failed|invalid",{E}}}[$__rate_interval]))'
                    f' / clamp_min(sum(rate(petabyte_jobs_total{{{E}}}[$__rate_interval])), 1e-9)', "fail %")],
                  unit="percent", steps=[(GREEN, None), (AMBER, 5), (RED, 20)], color="background",
                  desc="Alert-ready: PetabyteJobFailureSpike fires >20%."))
    p.append(stat(c, "API p95 latency",
                  [(f"histogram_quantile(0.95, sum by (le) (rate(petabyte_http_request_duration_seconds_bucket{{{E}}}[5m])))",
                    "p95")], unit="s", steps=[(GREEN, None), (AMBER, 1), (RED, 1.5)], color="background"))

    p.append(rowp(c, "Money today — $payment_mode only (TEST and LIVE never mixed)"))
    p.append(text(c, "", "**Showing `$payment_mode` money only.** `payment_mode` is single-select, so "
                  "these tiles can never sum TEST into LIVE (or vice-versa). Switch the variable to see "
                  "the other mode.", w=24, h=2))
    p.append(stat(c, "GMV today", [(f"sum(increase(petabyte_gmv_captured_minor_total{{{M}}}[24h])) / 100",
                                    "GMV")], unit="currencyUSD", w=5,
                  desc="Gross captured in the last 24h for the selected mode."))
    p.append(stat(c, "Platform fees today",
                  [(f"sum(increase(petabyte_platform_fees_minor_total{{{M}}}[24h])) / 100", "fees")],
                  unit="currencyUSD", w=5))
    p.append(stat(c, "Seller payable (outstanding)",
                  [(f"sum(petabyte_seller_payable_minor{{{M}}}) / 100", "owed")],
                  unit="currencyUSD", w=5, desc="Earned by sellers, not yet paid out (owed states)."))
    p.append(stat(c, "Payment success rate",
                  [(f'100 * sum(rate(petabyte_payment_captures_total{{outcome="success",{M}}}[$__rate_interval]))'
                    f' / clamp_min(sum(rate(petabyte_payment_captures_total{{{M}}}[$__rate_interval])), 1e-9)',
                    "success %")], unit="percent", w=5,
                  steps=[(RED, None), (AMBER, 95), (GREEN, 98)], color="background"))
    p.append(stat(c, "Seller earnings today",
                  [(f"sum(increase(petabyte_seller_earnings_minor_total{{{M}}}[24h])) / 100", "net")],
                  unit="currencyUSD", w=4))

    p.append(rowp(c, "Trends"))
    p.append(ts(c, "GMV & fees per hour ($payment_mode)",
                [(f"sum(increase(petabyte_gmv_captured_minor_total{{{M}}}[1h])) / 100", "GMV/h"),
                 (f"sum(increase(petabyte_platform_fees_minor_total{{{M}}}[1h])) / 100", "fees/h")],
                unit="currencyUSD"))
    p.append(ts(c, "Jobs completed vs failed",
                [(f'sum(rate(petabyte_jobs_total{{job_status=~"completed|validated",{E}}}[$__rate_interval]))', "completed"),
                 (f'sum(rate(petabyte_jobs_total{{job_status=~"failed|invalid",{E}}}[$__rate_interval]))', "failed")],
                unit="ops"))
    return dashboard("petabyte-executive", "Petabyte — Executive Overview",
                     ["petabyte", "executive"], [ENV, PAYMODE], p)


def d_marketplace():
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    p.append(rowp(c, "Supply"))
    for title, metric in [("Sellers online", "petabyte_sellers_online"),
                          ("Sellers registered", "petabyte_sellers_registered"),
                          ("Agents online", "petabyte_agents_online"),
                          ("GPUs online", "petabyte_gpus_online"),
                          ("GPUs available", "petabyte_gpus_available"),
                          ("GPUs reserved", "petabyte_gpus_reserved")]:
        p.append(stat(c, title, [(f"sum({metric}{{{E}}})", "")], w=4))
    p.append(stat(c, "Available GPU-hours", [(f"sum(petabyte_available_gpu_hours{{{E}}})", "GPU-h")], w=6))
    p.append(stat(c, "Jobs running", [(f"sum(petabyte_jobs_running{{{E}}})", "running")], w=6))
    p.append(stat(c, "Sellers stale (heartbeat lost)", [(f"sum(petabyte_sellers_stale{{{E}}})", "stale")],
                  w=6, steps=[(GREEN, None), (AMBER, 1), (RED, 3)], color="background"))
    p.append(stat(c, "Job success ratio (30m)", [(f"petabyte:job_success_ratio{{{E}}}", "success")],
                  unit="percentunit", w=6, steps=[(RED, None), (AMBER, 0.9), (GREEN, 0.98)]))

    p.append(rowp(c, "Supply over time & mix"))
    p.append(ts(c, "GPU supply", [(f"sum(petabyte_gpus_online{{{E}}})", "online"),
                                  (f"sum(petabyte_gpus_available{{{E}}})", "available"),
                                  (f"sum(petabyte_gpus_reserved{{{E}}})", "reserved")]))
    p.append(barchart(c, "Online GPUs by class", f"sum by (gpu_class) (petabyte_gpus_by_model{{{E}}})",
                      "{{gpu_class}}", w=6))
    p.append(barchart(c, "Online GPUs by country", f"sum by (country) (petabyte_gpus_by_country{{{E}}})",
                      "{{country}}", w=6))

    p.append(rowp(c, "Demand & flow"))
    p.append(ts(c, "Job throughput by status",
                [(f"sum by (job_status) (rate(petabyte_jobs_total{{{E}}}[$__rate_interval]))", "{{job_status}}")],
                unit="ops", stack=True))
    p.append(ts(c, "Transaction transitions",
                [(f"sum by (to_state) (rate(petabyte_transaction_transitions_total{{{E}}}[$__rate_interval]))",
                  "{{to_state}}")], unit="ops"))
    p.append(ts(c, "Reservation conflicts",
                [(f"sum(rate(petabyte_reservation_conflicts_total{{{E}}}[$__rate_interval]))", "conflicts/s")],
                unit="ops", steps=[(GREEN, None), (AMBER, 1)]))
    p.append(ts(c, "GPU routing p95",
                [(f"histogram_quantile(0.95, sum by (le) (rate(petabyte_routing_duration_seconds_bucket{{{E}}}[5m])))",
                  "p95")], unit="s"))
    p.append(ts(c, "Seller heartbeats & reaped",
                [(f"sum(rate(petabyte_seller_heartbeats_total{{{E}}}[$__rate_interval]))", "heartbeats/s"),
                 (f"sum(rate(petabyte_sellers_reaped_total{{{E}}}[$__rate_interval]))", "reaped/s")], unit="ops"))
    p.append(ts(c, "Seller job decisions",
                [(f"sum by (decision) (rate(petabyte_seller_job_decisions_total{{{E}}}[$__rate_interval]))",
                  "{{decision}}")], unit="ops"))
    return dashboard("petabyte-marketplace", "Petabyte — Marketplace",
                     ["petabyte", "marketplace"], [ENV], p)


def d_payments():
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    PM = 'payment_mode="$payment_mode",environment="$environment"'
    p.append(text(c, "TEST / LIVE isolation",
                  "**This dashboard shows `$payment_mode` money ONLY.** Every query is filtered "
                  "`payment_mode=\"$payment_mode\"`, and the variable is single-select — a LIVE panel "
                  "can never sum TEST transactions. Switch `payment_mode` to view the other stream.",
                  w=24, h=3))
    p.append(rowp(c, "Health ($payment_mode)"))
    p.append(stat(c, "Authorization success",
                  [(f'100 * sum(rate(petabyte_payment_authorizations_total{{outcome="success",{PM}}}[$__rate_interval]))'
                    f' / clamp_min(sum(rate(petabyte_payment_authorizations_total{{{PM}}}[$__rate_interval])),1e-9)',
                    "auth %")], unit="percent", steps=[(RED, None), (AMBER, 95), (GREEN, 98)],
                  color="background", w=6))
    p.append(stat(c, "Capture success",
                  [(f'100 * sum(rate(petabyte_payment_captures_total{{outcome="success",{PM}}}[$__rate_interval]))'
                    f' / clamp_min(sum(rate(petabyte_payment_captures_total{{{PM}}}[$__rate_interval])),1e-9)',
                    "capture %")], unit="percent", steps=[(RED, None), (AMBER, 98), (GREEN, 99)],
                  color="background", w=6))
    p.append(stat(c, "Capture failure ratio",
                  [(f"petabyte:capture_failure_ratio{{{PM}}}", "fail")], unit="percentunit",
                  steps=[(GREEN, None), (AMBER, 0.02), (RED, 0.05)], color="background", w=6,
                  desc="Alert-ready: PetabyteCaptureFailureSpike fires >2%."))
    p.append(stat(c, "Capture p95 latency",
                  [(f"histogram_quantile(0.95, sum by (le) (rate(petabyte_payment_capture_duration_seconds_bucket{{{PM}}}[5m])))",
                    "p95")], unit="s", w=6))
    p.append(rowp(c, "Authorizations, captures, transfers ($payment_mode)"))
    p.append(ts(c, "Payment intents & authorizations",
                [(f"sum by (outcome) (rate(petabyte_payment_intent_attempts_total{{{PM}}}[$__rate_interval]))", "intent {{outcome}}"),
                 (f"sum by (outcome) (rate(petabyte_payment_authorizations_total{{{PM}}}[$__rate_interval]))", "auth {{outcome}}")],
                unit="ops"))
    p.append(ts(c, "Captures & transfers by outcome",
                [(f"sum by (outcome) (rate(petabyte_payment_captures_total{{{PM}}}[$__rate_interval]))", "capture {{outcome}}"),
                 (f"sum by (outcome) (rate(petabyte_seller_transfers_total{{{PM}}}[$__rate_interval]))", "transfer {{outcome}}")],
                unit="ops"))
    p.append(ts(c, "Refunds", [(f"sum(rate(petabyte_refunds_total{{{PM}}}[$__rate_interval]))", "refunds/s")], unit="ops", w=8))
    p.append(ts(c, "Money captured/hr ($payment_mode)",
                [(f"sum(increase(petabyte_gmv_captured_minor_total{{{PM}}}[1h]))/100", "GMV/h"),
                 (f"sum(increase(petabyte_seller_earnings_minor_total{{{PM}}}[1h]))/100", "seller/h"),
                 (f"sum(increase(petabyte_platform_fees_minor_total{{{PM}}}[1h]))/100", "fees/h")],
                unit="currencyUSD", w=16))

    p.append(rowp(c, "Webhooks & reconciliation"))
    p.append(ts(c, "Stripe webhooks by outcome",
                [(f"sum by (outcome) (rate(petabyte_webhooks_total{{{E}}}[$__rate_interval]))", "{{outcome}}")], unit="ops", w=8))
    p.append(stat(c, "Invalid webhook signatures (1h)",
                  [(f"sum(increase(petabyte_webhook_invalid_signature_total{{{E}}}[1h]))", "invalid")],
                  steps=[(GREEN, None), (RED, 1)], color="background", w=4))
    p.append(stat(c, "Duplicate webhooks (1h)",
                  [(f"sum(increase(petabyte_webhook_duplicate_total{{{E}}}[1h]))", "dupes")], w=4))
    p.append(stat(c, "Ledger balanced", [(f"min(petabyte_ledger_balanced{{{E}}})", "balanced")],
                  steps=[(RED, None), (GREEN, 1)], color="background", w=4,
                  desc="1 = double-entry ledger balances. 0 is a P0."))
    p.append(stat(c, "Reconciliation discrepancies (1h)",
                  [(f"sum(increase(petabyte_reconciliation_discrepancies_total{{{E}}}[1h]))", "diffs")],
                  steps=[(GREEN, None), (RED, 1)], color="background", w=4))

    p.append(rowp(c, "Payout backlog & TEST/LIVE guard"))
    p.append(stat(c, "Seller payable ($payment_mode)",
                  [(f"sum(petabyte_seller_payable_minor{{{PM}}})/100", "owed")], unit="currencyUSD", w=6))
    p.append(stat(c, "Unbatched payout obligations",
                  [(f"sum(petabyte_payout_obligations_unbatched{{{E}}})", "unbatched")], w=6))
    p.append(stat(c, "Oldest unbatched payout",
                  [(f"max(petabyte_oldest_unbatched_payout_age_seconds{{{E}}})", "age")], unit="s",
                  steps=[(GREEN, None), (AMBER, 1209600), (RED, 1728000)], color="background", w=6,
                  desc="Alert-ready: PetabytePayoutBacklogAging fires >20 days."))
    p.append(stat(c, "TEST/LIVE mismatch (must be 0)",
                  [('sum(rate(petabyte_payment_captures_total{payment_mode="live",environment!="production"}[10m]))'
                    ' + sum(rate(petabyte_payment_captures_total{payment_mode="test",environment="production"}[10m]))',
                    "mismatch")], steps=[(GREEN, None), (RED, 0.0001)], color="background", w=6,
                  desc="Live captures outside production, or test captures in production. Alert-ready."))
    p.append(logs(c, "Payment failure logs ($payment_mode)",
                  '{service="petabyte-api"} | json | event_name=~"settlement.capture.failed|seller.transfer.failed'
                  '|webhook.processing.failed|payment.authorization.requested" | payment_mode=~"$payment_mode|"'))
    return dashboard("petabyte-settlement", "Petabyte — Payments & Stripe",
                     ["petabyte", "payments", "settlement"], [ENV, PAYMODE], p)


def d_gpu():
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    GM = 'modelName=~"$gpu_model"'
    p.append(rowp(c, "Fleet (platform view)"))
    p.append(stat(c, "Agents online", [(f"sum(petabyte_agents_online{{{E}}})", "agents")], w=4,
                  steps=[(RED, None), (GREEN, 1)]))
    p.append(stat(c, "Sellers online", [(f"sum(petabyte_sellers_online{{{E}}})", "sellers")], w=4))
    p.append(stat(c, "Sellers stale", [(f"sum(petabyte_sellers_stale{{{E}}})", "stale")], w=4,
                  steps=[(GREEN, None), (AMBER, 1), (RED, 3)], color="background"))
    p.append(stat(c, "GPUs online", [(f"sum(petabyte_gpus_online{{{E}}})", "gpus")], w=4))
    p.append(stat(c, "GPUs reserved", [(f"sum(petabyte_gpus_reserved{{{E}}})", "reserved")], w=4))
    p.append(stat(c, "Available GPU-hours", [(f"sum(petabyte_available_gpu_hours{{{E}}})", "GPU-h")], w=4))
    p.append(barchart(c, "GPUs online by class", f"sum by (gpu_class) (petabyte_gpus_by_model{{{E}}})",
                      "{{gpu_class}}", w=12))
    p.append(ts(c, "Job execution p95 by GPU class",
                [(f"histogram_quantile(0.95, sum by (le, gpu_class) (rate(petabyte_job_duration_seconds_bucket{{{E}}}[10m])))",
                  "{{gpu_class}}")], unit="s", w=12))
    p.append(ts(c, "Job startup p95 by GPU class",
                [(f"histogram_quantile(0.95, sum by (le, gpu_class) (rate(petabyte_job_startup_seconds_bucket{{{E}}}[10m])))",
                  "{{gpu_class}}")], unit="s", w=12))
    p.append(ts(c, "Jobs by class & status",
                [(f"sum by (gpu_class, job_status) (rate(petabyte_jobs_total{{{E}}}[$__rate_interval]))",
                  "{{gpu_class}} {{job_status}}")], unit="ops", w=12))

    p.append(rowp(c, "GPU hardware — NVIDIA DCGM exporter (per-device)"))
    p.append(text(c, "", "Per-device GPU metrics come from the **DCGM exporter** (`DCGM_FI_DEV_*`). "
                  "These panels are empty until a `dcgm-exporter` scrape target is live (see "
                  "`prometheus.yml` job `dcgm-exporter`). Per-node identity stays on the exporter's "
                  "`Hostname`/`gpu` labels — never in an app metric.", w=24, h=2))
    p.append(gauge(c, "Avg GPU utilization", [(f"avg(DCGM_FI_DEV_GPU_UTIL{{{GM}}})", "util")],
                   unit="percent", steps=[(GREEN, None), (AMBER, 85), (RED, 95)], w=6))
    p.append(gauge(c, "Avg VRAM used",
                   [("100 * sum(DCGM_FI_DEV_FB_USED{" + GM + "}) / "
                     "clamp_min(sum(DCGM_FI_DEV_FB_USED{" + GM + "}) + sum(DCGM_FI_DEV_FB_FREE{" + GM + "}), 1)",
                     "vram")], unit="percent", steps=[(GREEN, None), (AMBER, 85), (RED, 95)], w=6))
    p.append(stat(c, "Max GPU temperature", [(f"max(DCGM_FI_DEV_GPU_TEMP{{{GM}}})", "temp")],
                  unit="celsius", steps=[(GREEN, None), (AMBER, 80), (RED, 85)], color="background", w=6,
                  desc="Alert-ready: PetabyteGPUTempHigh fires >85C."))
    p.append(stat(c, "GPU XID errors (10m)", [(f"sum(increase(DCGM_FI_DEV_XID_ERRORS{{{GM}}}[10m]))", "xid")],
                  steps=[(GREEN, None), (RED, 1)], color="background", w=6,
                  desc="Alert-ready: PetabyteGPUXidErrors."))
    p.append(ts(c, "GPU utilization by model", [(f"avg by (modelName) (DCGM_FI_DEV_GPU_UTIL{{{GM}}})", "{{modelName}}")],
                unit="percent", w=12))
    p.append(ts(c, "GPU temperature by host", [(f"max by (Hostname) (DCGM_FI_DEV_GPU_TEMP{{{GM}}})", "{{Hostname}}")],
                unit="celsius", w=12))
    p.append(table(c, "Per-GPU snapshot (util / temp / VRAM used)",
                   [T("avg by (Hostname, gpu, modelName) (DCGM_FI_DEV_GPU_UTIL{" + GM + "})", "util", instant=True, refid="A"),
                    T("max by (Hostname, gpu, modelName) (DCGM_FI_DEV_GPU_TEMP{" + GM + "})", "temp", instant=True, refid="B"),
                    T("sum by (Hostname, gpu, modelName) (DCGM_FI_DEV_FB_USED{" + GM + "})", "vram_used_mib", instant=True, refid="C")],
                   w=24, h=8))

    p.append(rowp(c, "Seller agent health (logs)"))
    p.append(ts(c, "Heartbeats received", [(f"sum(rate(petabyte_seller_heartbeats_total{{{E}}}[$__rate_interval]))", "beats/s")],
                unit="ops", w=8))
    p.append(stat(c, "Agents online vs GPUs registered (0 = fleet dark)",
                  [(f"sum(petabyte_agents_online{{{E}}})", "agents")], w=8,
                  steps=[(RED, None), (GREEN, 1)], color="background",
                  desc="Alert-ready: PetabyteAgentHeartbeatStale (agents==0 while GPUs>0)."))
    p.append(stat(c, "Sellers reaped (1h)", [(f"sum(increase(petabyte_sellers_reaped_total{{{E}}}[1h]))", "reaped")], w=8))
    p.append(logs(c, "Seller-agent errors & missed heartbeats",
                  '{service="petabyte-seller-agent"} | json | event_name=~"agent.heartbeat.missed'
                  '|job.execution.failed|result.validation.failed|seller.suspicious" or level="error"'))
    return dashboard("petabyte-seller-fleet", "Petabyte — Seller GPU Fleet",
                     ["petabyte", "gpu", "sellers"], [ENV, GPUMODEL], p)


def d_api():
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    p.append(rowp(c, "Golden signals"))
    p.append(stat(c, "Request rate", [(f"sum(rate(petabyte_http_requests_total{{{E}}}[$__rate_interval]))", "req/s")],
                  unit="reqps", w=5))
    p.append(stat(c, "5xx error ratio", [(f"petabyte:http_error_ratio{{{E}}}", "5xx")], unit="percentunit",
                  steps=[(GREEN, None), (AMBER, 0.01), (RED, 0.05)], color="background", w=5,
                  desc="Alert-ready: PetabyteAPIHighErrorRate fires >5%."))
    p.append(stat(c, "p95 latency (all routes)",
                  [(f"histogram_quantile(0.95, sum by (le) (rate(petabyte_http_request_duration_seconds_bucket{{{E}}}[5m])))",
                    "p95")], unit="s", steps=[(GREEN, None), (AMBER, 1), (RED, 1.5)], color="background", w=5,
                  desc="Alert-ready: PetabyteAPIP95LatencyHigh fires >1.5s."))
    p.append(stat(c, "In-flight requests", [(f"sum(petabyte_http_in_flight_requests{{{E}}})", "in-flight")], w=4))
    p.append(stat(c, "API up", [('min(up{job="petabyte-api"})', "up")], steps=[(RED, None), (GREEN, 1)],
                  color="background", w=5))
    p.append(rowp(c, "Latency & errors"))
    p.append(ts(c, "Request rate by status class",
                [(f"sum by (status_class) (rate(petabyte_http_requests_total{{{E}}}[$__rate_interval]))", "{{status_class}}")],
                unit="reqps", stack=True))
    p.append(ts(c, "p95 latency by route (recording rule)",
                [(f"topk(10, petabyte:http_request_duration_seconds:p95{{{E}}})", "{{route}}")], unit="s",
                exemplar=True, desc="Click an exemplar to jump to its Tempo trace."))
    p.append(table(c, "Top routes by request rate",
                   [T(f"topk(15, sum by (route) (rate(petabyte_http_requests_total{{{E}}}[5m])))", "", instant=True)],
                   unit="reqps", w=12))
    p.append(table(c, "Slowest routes (p95)",
                   [T(f"topk(15, petabyte:http_request_duration_seconds:p95{{{E}}})", "", instant=True)],
                   unit="s", w=12))
    p.append(rowp(c, "Auth, rate-limit, validation"))
    p.append(ts(c, "Auth failures by reason",
                [(f"sum by (reason) (rate(petabyte_auth_failures_total{{{E}}}[$__rate_interval]))", "{{reason}}")], unit="ops", w=8))
    p.append(ts(c, "Rate-limit blocks by route",
                [(f"topk(10, sum by (route) (rate(petabyte_ratelimit_blocks_total{{{E}}}[$__rate_interval])))", "{{route}}")],
                unit="ops", w=8))
    p.append(ts(c, "Authz denials & validation failures",
                [(f"sum(rate(petabyte_authz_denials_total{{{E}}}[$__rate_interval]))", "authz denied/s"),
                 (f"sum(rate(petabyte_validation_failures_total{{{E}}}[$__rate_interval]))", "validation/s")], unit="ops", w=8))
    p.append(logs(c, "Server errors & unhandled exceptions",
                  '{service="petabyte-api"} | json | event_name="unhandled.exception" or status_class="5xx"'))
    return dashboard("petabyte-api", "Petabyte — API Performance", ["petabyte", "api"], [ENV], p)


def d_infra():
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    p.append(rowp(c, "Component availability"))
    for title, expr in [("API", 'min(up{job="petabyte-api"})'), ("PostgreSQL", "min(pg_up)"),
                        ("Redis", "min(redis_up)"), ("OTel collector", 'min(up{job="otel-collector"})'),
                        ("Loki", 'min(up{job="loki"})'), ("Tempo", 'min(up{job="tempo"})')]:
        p.append(stat(c, title, [(expr, "up")], steps=[(RED, None), (GREEN, 1)], color="background", w=4))
    p.append(rowp(c, "PostgreSQL & Redis"))
    p.append(gauge(c, "PG connection pool used",
                   [("100 * sum(pg_stat_activity_count) / clamp_min(max(pg_settings_max_connections), 1)", "used")],
                   unit="percent", steps=[(GREEN, None), (AMBER, 75), (RED, 90)], w=8,
                   desc="Alert-ready: PetabyteDBPoolExhaustion >90%."))
    p.append(stat(c, "Postgres up", [("min(pg_up)", "pg_up")], steps=[(RED, None), (GREEN, 1)],
                  color="background", w=8, desc="Alert-ready: PetabyteDatabaseDown (pg_up==0)."))
    p.append(stat(c, "Redis up", [("min(redis_up)", "redis_up")], steps=[(RED, None), (GREEN, 1)],
                  color="background", w=8))
    p.append(rowp(c, "Host resources (node_exporter)"))
    p.append(ts(c, "Disk used % by mountpoint",
                [('100 * (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} '
                  '/ node_filesystem_size_bytes{fstype!~"tmpfs|overlay"})', "{{instance}} {{mountpoint}}")],
                unit="percent", steps=[(GREEN, None), (AMBER, 80), (RED, 85)], w=12,
                desc="Alert-ready: PetabyteDiskHigh >85%."))
    p.append(ts(c, "Memory used %",
                [("100 * (1 - node_memory_MemAvailable_bytes / clamp_min(node_memory_MemTotal_bytes, 1))",
                  "{{instance}}")], unit="percent", steps=[(GREEN, None), (AMBER, 85), (RED, 95)], w=12))
    p.append(ts(c, "Load average (1m)", [("node_load1", "{{instance}}")], unit="short", w=12))
    p.append(rowp(c, "Telemetry pipeline & queues"))
    p.append(stat(c, "Prometheus freshness",
                  [("time() - max(prometheus_tsdb_head_max_time_seconds)", "staleness")], unit="s",
                  steps=[(GREEN, None), (AMBER, 120), (RED, 300)], color="background", w=6,
                  desc="Alert-ready: PetabytePrometheusStale >5m."))
    p.append(stat(c, "OTel collector up", [('min(up{job="otel-collector"})', "up")],
                  steps=[(RED, None), (GREEN, 1)], color="background", w=6,
                  desc="Alert-ready: PetabyteOtelCollectorDown."))
    p.append(ts(c, "Telemetry export failures",
                [(f"sum by (exporter) (rate(petabyte_telemetry_export_failures_total{{{E}}}[$__rate_interval]))",
                  "{{exporter}}")], unit="ops", steps=[(GREEN, None), (RED, 0.0001)], w=12))
    p.append(ts(c, "Queue depth", [(f"sum by (queue) (petabyte_queue_depth{{{E}}})", "{{queue}}")],
                steps=[(GREEN, None), (AMBER, 500)], w=12))
    p.append(ts(c, "Oldest queued item (recording rule)",
                [(f"max by (queue) (petabyte:queue_oldest_seconds{{{E}}})", "{{queue}}")], unit="s", w=12))
    p.append(ts(c, "Redis lock outcomes",
                [(f"sum by (outcome) (rate(petabyte_lock_acquisitions_total{{{E}}}[$__rate_interval]))", "{{outcome}}")],
                unit="ops", w=12))
    return dashboard("petabyte-infra", "Petabyte — Infrastructure", ["petabyte", "infrastructure"], [ENV], p)


def d_security():
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    p.append(rowp(c, "Abuse & auth"))
    p.append(stat(c, "Auth failures (5m)", [(f"sum(increase(petabyte_auth_failures_total{{{E}}}[5m]))", "fails")],
                  steps=[(GREEN, None), (AMBER, 50), (RED, 300)], color="background", w=6,
                  desc="Alert-ready: PetabyteAuthFailureSpike >5/s."))
    p.append(stat(c, "Authz denials (5m)", [(f"sum(increase(petabyte_authz_denials_total{{{E}}}[5m]))", "denied")], w=6))
    p.append(stat(c, "Rate-limit blocks (5m)", [(f"sum(increase(petabyte_ratelimit_blocks_total{{{E}}}[5m]))", "blocked")], w=6))
    p.append(stat(c, "Validation failures (5m)", [(f"sum(increase(petabyte_validation_failures_total{{{E}}}[5m]))", "invalid")], w=6))
    p.append(ts(c, "Auth failures by reason",
                [(f"sum by (reason) (rate(petabyte_auth_failures_total{{{E}}}[$__rate_interval]))", "{{reason}}")], unit="ops", w=12))
    p.append(ts(c, "Rate-limit blocks by route",
                [(f"topk(10, sum by (route) (rate(petabyte_ratelimit_blocks_total{{{E}}}[$__rate_interval])))", "{{route}}")],
                unit="ops", w=12))

    p.append(rowp(c, "Payment & financial integrity risk"))
    p.append(stat(c, "Invalid webhook signatures (1h)",
                  [(f"sum(increase(petabyte_webhook_invalid_signature_total{{{E}}}[1h]))", "invalid")],
                  steps=[(GREEN, None), (RED, 1)], color="background", w=6,
                  desc="Alert-ready: PetabyteWebhookInvalidSignature."))
    p.append(stat(c, "Suspicious seller telemetry (1h)",
                  [(f"sum(increase(petabyte_seller_suspicious_total{{{E}}}[1h]))", "suspicious")],
                  steps=[(GREEN, None), (AMBER, 1), (RED, 10)], color="background", w=6))
    p.append(stat(c, "Ledger balanced", [(f"min(petabyte_ledger_balanced{{{E}}})", "balanced")],
                  steps=[(RED, None), (GREEN, 1)], color="background", w=6,
                  desc="0 = double-entry imbalance (P0). Alert: PetabyteLedgerUnbalancedHeartbeat."))
    p.append(stat(c, "Ledger imbalance events (15m)",
                  [(f"sum(increase(petabyte_ledger_imbalance_total{{{E}}}[15m]))", "events")],
                  steps=[(GREEN, None), (RED, 1)], color="background", w=6))
    p.append(stat(c, "TEST captures in production (must be 0)",
                  [('sum(rate(petabyte_payment_captures_total{payment_mode="test",environment="production"}[10m]))', "test@prod")],
                  steps=[(GREEN, None), (RED, 0.0001)], color="background", w=12,
                  desc="Alert-ready: PetabyteTestLiveModeMismatch."))
    p.append(stat(c, "LIVE captures outside production (must be 0)",
                  [('sum(rate(petabyte_payment_captures_total{payment_mode="live",environment!="production"}[10m]))', "live@nonprod")],
                  steps=[(GREEN, None), (RED, 0.0001)], color="background", w=12,
                  desc="Alert-ready: PetabyteTestLiveModeMismatch."))
    p.append(rowp(c, "Security event logs"))
    p.append(logs(c, "Security events (auth / authz / rate-limit / suspicious / exceptions)",
                  '{service=~"$service"} | json | event_name=~"auth.failed|authz.denied|ratelimit.blocked'
                  '|request.validation.failed|seller.suspicious|unhandled.exception|webhook.processing.failed"'))
    return dashboard("petabyte-security", "Petabyte — Security / Risk", ["petabyte", "security"],
                     [ENV, SERVICEVAR], p)


def d_trust():
    """Trust & Integrity — the verification moat, made visible. Every panel reads the
    scrape-time petabyte_* trust gauges emitted by main._marketplace_metrics (same honest
    counts as the public /trust page)."""
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    p.append(text(c, "", "**The verification moat, in numbers.** These are the same honest counts as "
                         "the public [/trust](https://petabyte.market/trust) page — no fabrication, "
                         "zeros mean zero. Attestation → benchmark-vs-public-reference → signed, "
                         "content-bound results → redundant re-execution → payout freeze on fraud."))
    p.append(rowp(c, "Verification coverage"))
    p.append(stat(c, "Attested GPUs", [(f"max(petabyte_attested_gpus{{{E}}})", "attested")],
                  color="background", steps=[(GREEN, None)], w=5,
                  desc="Listings backed by an Ed25519-signed hardware report (verifiable)."))
    p.append(stat(c, "Confidential nodes (fresh TEE)",
                  [(f"max(petabyte_confidential_nodes_active{{{E}}})", "confidential")], w=5,
                  desc="Nodes holding a fresh confidential attestation (fail-closed in prod)."))
    p.append(stat(c, "Verifiable receipts issued",
                  [(f"max(petabyte_verifiable_receipts{{{E}}})", "receipts")], w=7,
                  desc="Completed jobs whose node signature is retained for the buyer to re-verify."))
    p.append(stat(c, "Results bound to output bytes",
                  [(f"max(petabyte_results_content_bound{{{E}}})", "content-bound")], w=7,
                  desc="Results committing to sha256 of the real output bytes (quorum-comparable)."))
    p.append(barchart(c, "GPUs by trust tier",
                      f"max by (tier) (petabyte_trust_tier_gpus{{{E}}})", "{{tier}}", w=12,
                      desc="self_reported → agent_verified → benchmark_consistent; 'flagged' = a "
                           "benchmark that contradicted the claimed GPU model."))
    p.append(ts(c, "Completed jobs (lifetime)",
                [(f"max(petabyte_jobs_completed_total{{{E}}})", "completed")], unit="short", w=12,
                desc="Durable count — survives a seller going offline."))

    p.append(rowp(c, "Fraud caught & redundant verification"))
    p.append(stat(c, "Sellers frozen for fraud",
                  [(f"max(petabyte_sellers_fraud_flagged{{{E}}})", "frozen")],
                  color="background", steps=[(GREEN, None), (AMBER, 1)], w=6,
                  desc="Sellers with fraud on record (payouts frozen pending review) — the system "
                       "working, not a failure."))
    p.append(stat(c, "Suspicious seller telemetry (24h)",
                  [(f"sum(increase(petabyte_seller_suspicious_total{{{E}}}[24h]))", "suspicious")],
                  color="background", steps=[(GREEN, None), (AMBER, 1), (RED, 10)], w=6,
                  desc="Nodes whose reported telemetry didn't add up."))
    p.append(barchart(c, "Redundant re-execution (quorum) outcomes",
                      f"max by (status) (petabyte_quorum_checks{{{E}}})", "{{status}}", w=12,
                      desc="AGREED = honest majority; DIVERGENT/INCONCLUSIVE = a mismatch was "
                           "caught and held/frozen."))
    p.append(rowp(c, "Integrity event log"))
    p.append(logs(c, "Trust & integrity events (fraud freezes / suspicious / invalid results)",
                  '{service=~"$service"} | json | event_name=~"seller.suspicious'
                  '|result.validation.failed|seller.reaped.batch|unhandled.exception"'))
    return dashboard("petabyte-trust", "Petabyte — Trust & Integrity", ["petabyte", "trust"],
                     [ENV, SERVICEVAR], p)


def d_operations():
    """Operations across the product surfaces beyond raw GPU supply: VMs, distributed clusters,
    disk rental, teams, escrowed/pooled buyer money, the task queue, and login/auth health.
    Everything here is fed by the scrape-time ops gauges in main.py:_marketplace_metrics and the
    cluster/login counters in observability.py — see the admin console's Live-operations tiles."""
    c = Ctx()
    p = []
    E = 'environment="$environment"'
    p.append(rowp(c, "Product surfaces"))
    p.append(stat(c, "Active VMs", [(f"sum(petabyte_vms_active{{{E}}})", "VMs")],
                  desc="Buyer VMs running/starting/migrating right now."))
    p.append(stat(c, "Clusters running",
                  [(f'sum(petabyte_distributed_clusters{{status="running",{E}}})', "clusters")]))
    p.append(stat(c, "Disk-rental nodes", [(f"sum(petabyte_disk_rental_nodes{{{E}}})", "nodes")]))
    p.append(stat(c, "Teams", [(f"sum(petabyte_teams_total{{{E}}})", "teams")]))
    p.append(stat(c, "In escrow", [(f"sum(petabyte_escrow_held_usd{{{E}}})", "held")],
                  unit="currencyUSD"))
    p.append(stat(c, "GPU utilization",
                  [(f"100 * sum(petabyte_vms_active{{{E}}}) / clamp_min(sum(petabyte_vms_active{{{E}}})"
                    f" + sum(petabyte_gpus_available{{{E}}}), 1e-9)", "util %")],
                  unit="percent", steps=[(GREEN, None), (AMBER, 80), (RED, 95)], color="background",
                  desc="Active VMs / (active + available units)."))

    p.append(rowp(c, "Distributed clusters"))
    p.append(ts(c, "Clusters by status",
                [(f"sum by (status) (petabyte_distributed_clusters{{{E}}})", "{{status}}")], stack=True))
    p.append(ts(c, "Cluster formations per hour (by outcome)",
                [(f"sum by (outcome) (increase(petabyte_cluster_formations_total{{{E}}}[1h]))",
                  "{{outcome}}")]))
    p.append(stat(c, "Cluster formation success rate",
                  [(f'100 * sum(rate(petabyte_cluster_formations_total{{outcome="success",{E}}}[$__rate_interval]))'
                    f' / clamp_min(sum(rate(petabyte_cluster_formations_total{{{E}}}[$__rate_interval])), 1e-9)',
                    "success %")], unit="percent",
                  steps=[(RED, None), (AMBER, 80), (GREEN, 95)], color="background"))

    p.append(rowp(c, "VMs & task queue"))
    p.append(stat(c, "VM failovers (cumulative)",
                  [(f"sum(petabyte_vm_migrations_cumulative{{{E}}})", "migrations")]))
    p.append(stat(c, "Pending tasks", [(f"sum(petabyte_pending_tasks{{{E}}})", "queued")],
                  steps=[(GREEN, None), (AMBER, 5), (RED, 20)], color="background"))
    p.append(stat(c, "Oldest pending task",
                  [(f"max(petabyte_oldest_pending_task_age_seconds{{{E}}})", "age")], unit="s",
                  steps=[(GREEN, None), (AMBER, 60), (RED, 300)], color="background"))
    p.append(ts(c, "Active VMs & queue depth",
                [(f"sum(petabyte_vms_active{{{E}}})", "active VMs"),
                 (f"sum(petabyte_pending_tasks{{{E}}})", "pending tasks")]))

    p.append(rowp(c, "Buyer money held"))
    p.append(stat(c, "Buyer wallet balances",
                  [(f"sum(petabyte_wallet_balance_usd{{{E}}})", "wallets")], unit="currencyUSD"))
    p.append(stat(c, "Team pooled balances",
                  [(f"sum(petabyte_teams_pooled_balance_usd{{{E}}})", "teams")], unit="currencyUSD"))
    p.append(ts(c, "Escrow, wallets & team balances",
                [(f"sum(petabyte_escrow_held_usd{{{E}}})", "escrow"),
                 (f"sum(petabyte_wallet_balance_usd{{{E}}})", "wallets"),
                 (f"sum(petabyte_teams_pooled_balance_usd{{{E}}})", "teams")], unit="currencyUSD"))

    p.append(rowp(c, "Disk rental"))
    p.append(stat(c, "GB pledged", [(f"sum(petabyte_disk_rental_gb_pledged{{{E}}})", "GB")],
                  unit="decgbytes"))
    p.append(stat(c, "GB used", [(f"sum(petabyte_disk_rental_gb_used{{{E}}})", "GB")],
                  unit="decgbytes"))
    p.append(ts(c, "Disk pledged vs used (GB)",
                [(f"sum(petabyte_disk_rental_gb_pledged{{{E}}})", "pledged"),
                 (f"sum(petabyte_disk_rental_gb_used{{{E}}})", "used")], unit="decgbytes"))

    p.append(rowp(c, "Access & auth"))
    p.append(ts(c, "Logins per second (by outcome)",
                [(f"sum by (outcome) (rate(petabyte_logins_total{{{E}}}[$__rate_interval]))",
                  "{{outcome}}")], unit="ops"))
    p.append(stat(c, "Login failure rate",
                  [(f'100 * sum(rate(petabyte_logins_total{{outcome="failure",{E}}}[$__rate_interval]))'
                    f' / clamp_min(sum(rate(petabyte_logins_total{{{E}}}[$__rate_interval])), 1e-9)',
                    "fail %")], unit="percent",
                  steps=[(GREEN, None), (AMBER, 20), (RED, 50)], color="background"))
    p.append(ts(c, "Auth failures per second (by reason)",
                [(f"sum by (reason) (rate(petabyte_auth_failures_total{{{E}}}[$__rate_interval]))",
                  "{{reason}}")], unit="ops"))
    return dashboard("petabyte-operations", "Petabyte — Operations",
                     ["petabyte", "operations"], [ENV], p)


BUILDERS = [d_executive, d_marketplace, d_payments, d_gpu, d_api, d_infra, d_security, d_trust,
            d_operations]
FILES = {
    "petabyte-executive": "executive.json", "petabyte-marketplace": "marketplace.json",
    "petabyte-settlement": "payments.json", "petabyte-seller-fleet": "gpu-fleet.json",
    "petabyte-api": "api.json", "petabyte-infra": "infrastructure.json",
    "petabyte-security": "security.json", "petabyte-trust": "trust.json",
    "petabyte-operations": "operations.json",
}


def main():
    os.makedirs(OUT, exist_ok=True)
    written = []
    for build in BUILDERS:
        d = build()
        path = os.path.join(OUT, FILES[d["uid"]])
        with open(path, "w") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
            f.write("\n")
        written.append((os.path.basename(path), d["uid"], d["title"],
                        len([p for p in d["panels"] if p["type"] != "row"])))
    for name, uid, title, n in written:
        print(f"  {name:22} uid={uid:22} panels={n:2}  {title}")
    print(f"\nwrote {len(written)} dashboards to {OUT}")


if __name__ == "__main__":
    main()
