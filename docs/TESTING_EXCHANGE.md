# Testing exchange

The copy/paste bridge between Claude (sandboxed, can't SSH to your infra) and you (the
operator). Every command is ready to run as written. **Append-only:** when a section is
done, mark it `✅ COMPLETE` — don't delete it. New required actions go at the bottom under
a dated heading so the history stays intact.

## Machines (real values)

| Role | Address | Notes |
|---|---|---|
| Platform | `https://petabyte.market` (its Droplet) | API + Postgres + (optional) Redis |
| Buyer Droplet | `137.184.198.133` | runs the buyer→seller E2E driver |
| Seller GPU Droplet | `165.22.236.63` | GPU + seller agent |
| Observability server | set `OBSERVABILITY_SERVER_HOST` in GitHub | Collector/Prometheus/Grafana/Loki/Tempo |

**Secrets are never written here.** Where a secret is needed, export it in your shell first
(shown once, below). Do not paste secret values into files, screenshots, or commit them.

```bash
# Run ONCE per shell on each Droplet, from your secure notes (values NOT stored in git):
export BUYER_USER="testUser"
export BUYER_PASSWORD="<paste from your notes — do NOT commit>"      # marked once
export SELLER_USER="testUserSeller"
export SELLER_PASSWORD="<paste from your notes — do NOT commit>"     # marked once
```

---

# Platform server (`petabyte.market`)

**Purpose:** confirm the deploy is healthy, config preflight passes, and metrics/telemetry
are live. Run these from the platform Droplet (or via `ssh root@<platform-ip>`).

```bash
# Health
curl -fsS https://petabyte.market/healthz && echo
curl -fsS https://petabyte.market/readyz && echo
curl -fsS https://petabyte.market/health/observability | python3 -m json.tool

# Protected Prometheus metrics (needs the bearer token you set as PROMETHEUS_METRICS_TOKEN)
export PROMETHEUS_METRICS_TOKEN="<paste — do NOT commit>"
curl -fsS -H "Authorization: Bearer $PROMETHEUS_METRICS_TOKEN" \
  https://petabyte.market/internal/metrics | grep -E '^petabyte_(sellers_online|gpus_online|http_requests_total)' | head
```

**Expected output**
- `/healthz` → `{"status":"ok"}`
- `/readyz` → `{"status":"ready"}`
- `/health/observability` → `enabled:true`, `logging_json:true`, `redaction:true`, and
  `tracing.active` / `metrics.active` reflecting whether the collector endpoint is set.
- metrics → `petabyte_sellers_online`, `petabyte_gpus_online`, `petabyte_http_requests_total` lines.

**Success criteria:** all three health endpoints 200; metrics endpoint returns `petabyte_*`
series (403 without the token — that's correct, it's protected).

**Config preflight (before/after a deploy):**
```bash
cd /opt/lumaris   # or your checkout
# validate the resolved config for this environment (secrets shown only as SET/MISSING)
python3 scripts/validate_github_configuration.py --env-name "${ENVIRONMENT:-staging}"
```
Expected: `OK: configuration is valid.` (exit 0). Any `::error::` line blocks the deploy.

**Rollback:** if a deploy misbehaves, the previous release is the prior git SHA:
```bash
cd /root/petabyte && git log --oneline -5
sudo -u lumaris git -C /root/petabyte checkout <previous-sha> && sudo /opt/lumaris/deploy/update.sh
```

---

# Buyer Droplet (`137.184.198.133`)

**Purpose:** drive a full buyer→seller→settlement flow against `https://petabyte.market`
using **Stripe TEST mode only**.

```bash
ssh root@137.184.198.133

# Update the repo + deps
cd /opt/petabyte 2>/dev/null || (git clone https://github.com/BDR-Pro/petabyte /opt/petabyte && cd /opt/petabyte)
cd /opt/petabyte && git pull --ff-only
python3 -m pip install -q -r lumaris_api/requirements.txt

# Run the offline full-flow E2E (fake gateway, no GPU) to prove wiring locally
python3 scripts/e2e/local_e2e.py

# Inspect logs (structured JSON — pipe through jq if installed)
tail -n 200 /var/log/petabyte-e2e.log 2>/dev/null | (command -v jq >/dev/null && jq . || cat)
```

**Expected output:** `local buyer→seller→settlement E2E` completes with a printed
`transaction_id`, `trace_id`, and `job_id`; no `ERROR` lines.

**Success criteria:** E2E exits 0; you can copy the `transaction_id` into the Grafana
**Transaction Trace** dashboard and see the full timeline.

**Diagnostics if it fails:**
```bash
bash /opt/petabyte/docs/scripts/collect_platform_logs.sh
```

---

# Seller GPU Droplet (`165.22.236.63`)

**Purpose:** verify GPU + agent, register the seller, and confirm telemetry reaches the
platform via **outbound** calls (no inbound ports opened on this machine).

```bash
ssh root@165.22.236.63

# GPU + CUDA + Docker + NVIDIA Container Toolkit
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi

# Install / update the seller agent (uses the platform's authenticated API)
bash /opt/petabyte/docs/scripts/install_gpu_dependencies.sh
export PETABYTE_API_URL="https://petabyte.market"
export PETABYTE_API_KEY="<node key from POST /create_api_key — do NOT commit>"
export PETABYTE_SPEC_ID="<the spec id this node serves>"
sudo systemctl restart petabyte-agent 2>/dev/null || python3 /opt/petabyte/lumaris_agent/task_fetcher.py &

# Verify the agent's outbound telemetry + heartbeat
bash /opt/petabyte/docs/scripts/debug_gpu_agent.sh
```

**Expected output**
- `nvidia-smi` lists the GPU; the CUDA container also prints the GPU.
- Agent logs (JSON) show `event_name:"agent.startup"` then repeating
  `event_name:"agent.heartbeat"`; the platform's `/internal/metrics` shows
  `petabyte_seller_heartbeats_total` increasing and `petabyte_sellers_online >= 1`.

**Success criteria checklist** (update in place):
- [ ] GPU detected (`nvidia-smi`)
- [ ] CUDA working (container `nvidia-smi`)
- [ ] Docker + NVIDIA Container Toolkit OK
- [ ] Seller agent connected (heartbeat 200)
- [ ] `petabyte_sellers_online` incremented on the platform
- [ ] Buyer login tested
- [ ] Stripe TEST PaymentIntent created + captured
- [ ] Result validated
- [ ] Seller test transfer created
- [ ] One `transaction_id` traces end-to-end in Grafana

**Failure handling:** if heartbeats don't appear on the platform, open
`docs/DEBUG_EXCHANGE.md` (request #1) and run the listed script; send back the output.

---

## Observability verification (any machine that can reach the obs server)

```bash
# Point at your observability server, then run the smoke test's REMOTE tier.
export OTEL_EXPORTER_OTLP_ENDPOINT="http://<obs-host>:4317"
export TEMPO_URL="http://<obs-host>:3200"
export LOKI_URL="http://<obs-host>:3100"
export GRAFANA_URL="http://<obs-host>:3000"
python3 /opt/petabyte/scripts/observability_smoke_test.py
```
**Expected:** local checks `ok`; the remote checks (Tempo/Loki/Grafana) turn from `skip`
to `ok`. `0 failed`. No secret appears in any emitted event.

---

<!-- Append new dated sections below; mark finished sections ✅ COMPLETE. Never overwrite. -->
