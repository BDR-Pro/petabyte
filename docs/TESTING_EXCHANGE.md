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

## 2026-08-06 — Observability stack repair (Droplet `/opt/petabyte-observability`)

Fixes the five known failures (Grafana datasource escape, OTel `address` key, Tempo
schema, Loki + Redis health checks) and pins all images. Idempotent + safe to rerun; it
backs up first, preserves volumes + credentials, and never deletes data or prints secrets.
The full copy/paste-without-file-transfer script is **DEBUG REQUEST #2** in
`docs/DEBUG_EXCHANGE.md`.

**Exact run command** (on the observability Droplet, as root):
```bash
cd /opt/petabyte-observability
sudo bash /opt/petabyte/docs/scripts/repair_observability_stack.sh
```

**Expected output (tail):**
```
================ REPAIR SUCCESSFUL ================
   OK   Grafana healthy (http://localhost:3000/api/health)
   OK   Prometheus healthy (http://localhost:9090/-/healthy)
   OK   Loki healthy (http://localhost:3100/ready)
   OK   Tempo healthy (http://localhost:3200/ready)
   OK   OTel Collector healthy (http://localhost:13133/)
   OK   Redis PONG (authenticated)
   OK   Node Exporter running
   OK   cAdvisor running
Backup: /opt/petabyte-observability/backups/<ts>   (credentials + volumes preserved)
```

**Success criteria:**
- Exit code 0 and the `REPAIR SUCCESSFUL` banner.
- `docker compose ps` shows every service `running`/`healthy` with **pinned** image tags
  (no `:latest`).
- No Grafana provisioning error in `docker compose logs grafana`.
- No `invalid key: address` in `docker compose logs otel-collector`.
- No `field ingester/compactor not found` in `docker compose logs tempo`.
- No secret value appears anywhere in the output.

**Independent verification commands** (run after the script):
```bash
cd /opt/petabyte-observability
docker compose ps
docker compose config | grep -E 'image:'                 # confirm pinned versions, no :latest
curl -fsS http://localhost:3000/api/health; echo         # Grafana {"database":"ok"...}
curl -fsS http://localhost:9090/-/healthy; echo          # Prometheus Healthy
curl -fsS http://localhost:3100/ready; echo              # Loki: ready
curl -fsS http://localhost:3200/ready; echo              # Tempo: ready
curl -fsS http://localhost:13133/; echo                  # OTel health_check: 200
docker compose exec -T redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping'  # PONG
docker compose logs grafana --tail=50 | grep -i provisioning || echo "no provisioning errors"
```

**Rollback command** (restores the timestamped backup and restarts):
```bash
sudo bash /opt/petabyte/docs/scripts/repair_observability_stack.sh --rollback
# or a specific backup:
sudo bash /opt/petabyte/docs/scripts/repair_observability_stack.sh --rollback <ts>
```

_Status: ⏳ WAITING FOR OPERATOR EXECUTION — do not mark COMPLETE until the script output is
pasted back and all services report healthy._

---

<!-- Append new dated sections below; mark finished sections ✅ COMPLETE. Never overwrite. -->

## 2026-08-07 — Load / GPU smoke suite (real Buyer → Platform → Seller → GPU chain)

Proves Petabyte can create **measurable load through the real marketplace path** — not that
a GPU merely exists. Commands are idempotent; each writes a machine-readable report under
`artifacts/`. GPU assertions require a Seller GPU box (Docker + NVIDIA runtime); on a runner
without a GPU they report `EXTERNAL_GPU_TEST_REQUIRED` and never fake PASS.

### [PLATFORM]

```bash
# Start / check the API (its Droplet)
sudo systemctl status lumaris-api

# Verify PostgreSQL (concurrency correctness REQUIRES Postgres, not SQLite)
psql "$DATABASE_URL" -c "select version();"

# Readiness (DB-checked) + liveness
curl -fsS https://petabyte.market/readyz && echo
curl -fsS https://petabyte.market/healthz && echo

# Watch jobs / bookings + financial heartbeat while a load run is in flight
watch -n 2 'curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" https://petabyte.market/admin/financial-integrity | jq'

# Watch structured logs / metrics
journalctl -u lumaris-api -f | jq -R 'fromjson? // .'
curl -fsS -H "Authorization: Bearer $PROMETHEUS_METRICS_TOKEN" https://petabyte.market/internal/metrics | grep petabyte_
```

### [BUYER]  (concurrent load through the REAL API)

```bash
cd /opt/petabyte

# Postgres is required for a real concurrency claim; point at the platform DB (test DB!).
export DATABASE_URL='postgresql+psycopg2://USER:PASS@127.0.0.1:5432/petabyte_test'

SMOKE_BUYERS=10 SMOKE_JOBS_PER_BUYER=2 SMOKE_CONCURRENCY=10 \
SMOKE_SELLERS=2 SMOKE_SELLER_CAPACITY=2 \
make smoke-load
# -> artifacts/SMOKE_LOAD_REPORT.json  (+ .md)
```

Expected: `FINAL: PASS` with every invariant ok — `capacity_never_oversold`,
`capacity_never_negative`, `no_capacity_leak`, `contention_enforced`, `no_real_failures`,
`cross_buyer_isolation`, `ledger_balanced`, `platform_stayed_ready`. Under contention some
jobs are correctly `jobs_rejected_capacity` (capacity is time-bound to a rental; a 409 at
booking is the limit binding, not a failure).

### [SELLER GPU]  (real GPU compute in the workload runtime)

```bash
# 1. host GPU present?
nvidia-smi

# 2. GPU visible INSIDE the Petabyte workload runtime (NOT host-only)
docker run --rm --gpus all --cap-drop ALL --security-opt no-new-privileges \
  pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime nvidia-smi -L

# 3. bounded GPU load + measured utilization (this is the assertion, not the human watching)
cd /opt/petabyte
SMOKE_GPU_REQUIRED=1 SMOKE_MIN_GPU_UTILIZATION=20 make smoke-gpu
# -> artifacts/SMOKE_GPU_REPORT.json  (peak/avg utilization, peak mem, duration)

# 4. the FULL chain (marketplace load + GPU compute), merged report
make smoke-e2e-gpu   # -> artifacts/SMOKE_E2E_GPU_REPORT.json

# Optional live human view (assertions do NOT depend on this):
watch -n 1 nvidia-smi
```

To prove buyer load **causes** GPU load end to end on one box: run the **real seller agent**
against the platform on this GPU Droplet, then drive `make smoke-load` at it — the agent
claims the buyer's job and executes it in a GPU container while `nvidia-smi` sampling records
utilization during the job's running interval. That on-hardware correlation is
`EXTERNAL_GPU_TEST_REQUIRED` (it cannot run on a GPU-less CI runner).

_Status: ⏳ WAITING FOR OPERATOR EXECUTION on the Seller GPU Droplet — paste
`artifacts/SMOKE_GPU_REPORT.json` back to mark ✅ COMPLETE._

---

# 2026-08-07 — REAL STRIPE TEST + REMOTE GPU E2E (one command)

The whole buyer → Stripe TEST → GPU seller → capture → **held** payout flow is now a single
command. No more copying JWTs, PaymentIntent IDs, `curl`, or hand-built JSON, and no calling
`/dispatch` twice — the runner dispatches **once** and polls `GET /payments/{tx}`.

## One-time setup

1. **Platform env** — the served API chooses its gateway explicitly (it will refuse to start
   otherwise; there is no silent fake-money fallback):

   ```bash
   export STRIPE_GATEWAY=real
   export STRIPE_MODE=test
   export PAYMENTS_MODE=sandbox
   export STRIPE_SECRET_KEY=sk_test_...        # a TEST key — a live key is rejected
   export STRIPE_PUBLISHABLE_KEY=pk_test_...
   export PUBLIC_BASE_URL=https://petabyte.market   # needed for Connect onboarding return URLs
   ```

2. **Seller** completes real Stripe Connect **TEST** onboarding once, and the agent is
   installed and running:

   ```bash
   systemctl status petabyte-agent
   ```

3. Start the API from the **repo root** (this now works — no `cd lumaris_api` needed):

   ```bash
   python -m uvicorn lumaris_api.main:app --host 0.0.0.0 --port 8000
   ```

## Repeated E2E

```bash
# same shell must have STRIPE_SECRET_KEY=sk_test_... exported
export STRIPE_SECRET_KEY=sk_test_...

# safe check first — creates NO payment:
make e2e-preflight SPEC=<public-spec-id> E2E_API=http://127.0.0.1:8000

# the full run:
make e2e-real SPEC=<public-spec-id> E2E_API=http://127.0.0.1:8000
# extra options via ARGS, e.g. a longer GPU workload + verbose:
make e2e-real SPEC=<public-spec-id> ARGS='--gpu-test-seconds 45 --verbose'
```

The seller side needs **no command** if the agent is already running.

Find `<public-spec-id>` (the string handle, e.g. `e1qdx89mtqjq` — **not** the numeric DB id
and **not** the seller id) in the public marketplace:

```bash
curl -fsS http://127.0.0.1:8000/marketplace/specs | python3 -m json.tool | grep '"id"'
```

## What PASS means

The runner drives: preflight → buyer auth → `/payments/authorize` (real Stripe TEST
PaymentIntent, `capture_method=manual`) → confirm the PI with the **Stripe SDK** (test card
`pm_card_visa`, no Stripe CLI needed) → assert `livemode=false` + `requires_capture` →
`POST /payments/{tx}/confirm` (Petabyte re-verifies Stripe server-side) → reserve →
**dispatch once** → seller agent runs the bounded GPU workload → `/jobs/result` → automatic
meter + capture → poll `GET` → verify capture / fee / seller-net / receipt / timeline.

**Seller payout is intentionally PENDING.** Capture creates a *held* payout obligation with a
14-day risk hold; `transferred_amount` stays `0` until the hold elapses and the biweekly batch
runs. That is the correct terminal E2E state:

```
Seller settlement
  Transferred now        $0.00
  Status                 PENDING BY DESIGN (held for the configured payout hold)
```

Artifacts (secrets redacted — never any key, `client_secret`, JWT, or webhook secret):

```
artifacts/REAL_E2E_REPORT.json
artifacts/REAL_E2E_REPORT.txt
```

## Safety (built in, no override)

- Refuses `sk_live_` / `rk_live_` keys and any PaymentIntent with `livemode=true` — aborts
  before touching money; there is no `--force`.
- `simulate-card` is **FAKE-GATEWAY ONLY** and returns 404 under real Stripe; the runner never
  uses it — it confirms via the Stripe SDK.
- A served API refuses to start with `STRIPE_GATEWAY` unset (no silent fake gateway). For
  offline self-tests only, `PETABYTE_OFFLINE_TEST=1` pins the fake gateway loudly.
- A **fake** Connect account can never be reused once the process runs the **real** gateway
  (and vice versa) — `ConnectedAccountModeMismatch` fails closed. If you see it, remove that
  seller's stale account and re-onboard under the real gateway.

## Webhook testing (optional — separate from the basic E2E)

The basic E2E does **not** need the Stripe CLI. Webhook signature handling is covered by its
own suite (`stripe_test.py`: valid/invalid signature, replay, duplicate, unknown tx,
TEST/LIVE mismatch). For a live webhook loop:

```bash
stripe listen --forward-to http://127.0.0.1:8000/webhooks/stripe
# use the printed whsec_... as STRIPE_WEBHOOK_SECRET; signatures are always verified.
```

## Payout-eligibility tests (no 14-day wait)

The hold boundary is unit-tested with an **injected clock** — no wall-clock change, no HTTP
override:

```bash
cd lumaris_api && python e2e_safety_test.py     # day 0 / 13 / exact-14 boundary / day 15
```

## Troubleshooting (operator-safe error codes)

| Symptom | Meaning / fix |
|---|---|
| `CONNECTED_ACCOUNT_MODE_MISMATCH` | A fake account exists under the real gateway. Remove the seller's stale `connected_accounts` row, re-onboard. |
| `CONNECT_RETURN_URL_MISSING` (503) | Set `PUBLIC_BASE_URL` (or `CONNECT_RETURN_URL`/`CONNECT_REFRESH_URL`). |
| Preflight `GPU spec … not listed` | Spec isn't publicly bookable: not attested, no units, or seller not payout-ready. |
| `STRIPE_AUTHORIZATION` expected `requires_capture` | PaymentIntent needs redirect handling; the runner passes a `return_url`. Check the key is `sk_test_`. |
| `ABORT: … sk_live_` | You exported a live key. The runner never runs on live money. |
| API won't start, `STRIPE_GATEWAY is not set` | Export `STRIPE_GATEWAY=real` (or `fake`). No silent fallback. |

_Status: ⏳ WAITING FOR OPERATOR EXECUTION on the Platform Droplet — run `make e2e-real SPEC=...`
and paste `artifacts/REAL_E2E_REPORT.txt` back to mark ✅ COMPLETE._
