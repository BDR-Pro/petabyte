# Debug exchange

When Claude needs information from your servers, it appends a **numbered debug request**
here instead of just asking. You open the latest `PENDING` request, run the one script (or
commands), and paste the output back. Claude then marks it `RESOLVED`/`FAILED` and appends
the next step.

**Protocol**
- Requests are numbered and **never deleted**.
- Status is one of: `PENDING` (waiting on you) · `RUNNING` (you're executing) ·
  `RESOLVED` (fixed/understood) · `FAILED` (needs another round).
- Scripts referenced live in `docs/scripts/` (bash, `set -Eeuo pipefail`, print progress,
  collect diagnostics, meaningful exit codes).
- Secrets are never printed into this file. Export them in your shell first.

---

## DEBUG REQUEST #1 — verify seller telemetry reaches the platform  · Status: **PENDING**

**Reason:** confirm the ephemeral-seller telemetry path works end to end — the seller
agent's OUTBOUND heartbeat is observed by the platform, increments
`petabyte_seller_heartbeats_total`, and shows up as `petabyte_sellers_online >= 1`.

**Run on:** Seller GPU Droplet (`165.22.236.63`), then the Platform server.

**Commands (seller):**
```bash
bash /opt/petabyte/docs/scripts/debug_gpu_agent.sh
```
**Commands (platform):**
```bash
export PROMETHEUS_METRICS_TOKEN="<paste — do NOT commit>"
curl -fsS -H "Authorization: Bearer $PROMETHEUS_METRICS_TOKEN" \
  https://petabyte.market/internal/metrics \
  | grep -E '^petabyte_(sellers_online|seller_heartbeats_total|gpus_online|agents_online)'
```

**Expected information / success:**
- Agent JSON logs show `agent.startup` then repeating `agent.heartbeat`.
- `curl https://petabyte.market/heartbeat`-driven counters rise:
  `petabyte_seller_heartbeats_total` increasing, `petabyte_sellers_online >= 1`,
  `petabyte_gpus_online >= 1`.
- No `authentication` / `403` / `404` errors in the agent log.

**Next action after you paste results:** if heartbeats are sent but counters don't move →
check API-key scope (`node`) and `PETABYTE_SPEC_ID` ownership; if the agent can't POST →
DNS/TLS/egress from the seller box (it must reach `https://petabyte.market` outbound); if
counters move but `sellers_online` stays 0 → heartbeat staleness/`HEARTBEAT_TIMEOUT_S`.

---

<!-- Append DEBUG REQUEST #2, #3, ... below. Increment the number. Never delete. -->
