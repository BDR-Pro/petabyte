#!/usr/bin/env bash
# run_tests.sh — run every suite against BOTH engines.
#
# WHY BOTH:
#   SQLite is fast and needs no setup, but it is the wrong engine to be confident on:
#     * no decimal type   -> NUMERIC(20,8) round-trips through float; "exact money"
#                            is unproven no matter how green the suite looks
#     * serialises writers -> whole classes of race condition cannot occur
#     * no advisory locks  -> the maintenance leader election is a silent no-op
#   Production is Postgres. A green SQLite run is a smoke signal, not confidence.
#
# USAGE
#   ./run_tests.sh                 # SQLite only (fast, for the inner loop)
#   ./run_tests.sh --postgres      # both engines (what CI must run)
#
# CI must use --postgres. Money and concurrency bugs live where SQLite can't look.
set -euo pipefail
cd "$(dirname "$0")"

GREEN=$'\e[32m'; RED=$'\e[31m'; BOLD=$'\e[1m'; OFF=$'\e[0m'
fail=0

run_suite () {   # run_suite <label> <cmd...>
  local label="$1"; shift
  echo ""
  echo "${BOLD}--- $label ---${OFF}"
  if "$@"; then
    echo "${GREEN}ok${OFF}  $label"
  else
    echo "${RED}FAILED${OFF}  $label"
    fail=1
  fi
}

# ---------------------------------------------------------------- SQLite
echo "${BOLD}=========== SQLite (fast path) ===========${OFF}"
unset DATABASE_URL || true
rm -f smoke.db* adv.db* ../lumaris_gateway/tunnel.db*
run_suite "smoke (sqlite)"        python smoke_test.py
run_suite "adversarial (sqlite)"  python adversarial_test.py
run_suite "stripe connect (sqlite)" python stripe_test.py
run_suite "payout routing (sqlite)" python payout_test.py
run_suite "email (mailgun, offline)" python email_test.py
run_suite "matmul result validation (offline)" python matmul_validation_test.py
run_suite "account (reset + cal webhook + demo notify)" python account_test.py
run_suite "wallet (add funds via stripe checkout)" python wallet_test.py
run_suite "seller integrity audits (anti-fraud)" python seller_audit_test.py
run_suite "quorum verification (redundant re-execution)" python quorum_test.py
run_suite "real-job re-verification (content-hash quorum on real work)" python reverify_test.py
run_suite "marketplace intelligence (health/routing/trust/timeline)" python marketplace_test.py
run_suite "github config (manifest/validator/generator/drift)" python config_test.py
run_suite "ENV_VARS bundle (parser/secret-guard/precedence)" python env_vars_test.py
run_suite "observability (correlation/redaction/cardinality/degrade)" python observability_test.py
run_suite "product analytics (posthog funnel mirror; off-by-default, no PII)" python product_analytics_test.py
run_suite "sentry (degrade-safe init + before_send redaction)" python sentry_test.py
run_suite "seller payable metric (mode-separated payout gauge)" python seller_payable_metric_test.py
run_suite "funding metrics (canonical, scope-separated, honest)" python funding_metrics_test.py
run_suite "db invariants (money-impossible states rejected at DB layer)" python db_invariants_test.py
run_suite "security (ip-spoof / cross-tenant refs / stored-xss at write time)" python security_test.py
run_suite "confidential computing (TEE fail-closed in prod + attestation freshness)" python tee_test.py
run_suite "gpu benchmark authenticity (score vs public reference band)" python gpu_benchmark_test.py
run_suite "authenticity training dataset (feature rows + labels export)" python training_data_test.py
run_suite "seller earnings forecast (net/hr exact + honest estimates)" python earnings_test.py
run_suite "pricing engine (cloud-anchored, demand+trust, explainable, clamped)" python pricing_engine_test.py
run_suite "reservation reclaim (abandoned GPU capacity)" python reservation_reclaim_test.py
run_suite "database backup to S3 (disaster recovery: dump/gzip/sha256/retention/verify)" python backup_test.py
run_suite "sanctions screen (free public OFAC: country embargo + SDN crypto address, fail-closed)" python sanctions_test.py
run_suite "observability smoke (local tier; remote skipped offline)" \
          bash -c "cd .. && python scripts/observability_smoke_test.py"
run_suite "grafana dashboards (metric-existence + generator determinism)" \
          bash -c "cd .. && python observability/grafana/validate_dashboards.py && \
                   python observability/grafana/build_dashboards.py && \
                   git diff --exit-code observability/grafana/dashboards"
run_suite "grafana provisioning (provider<->mount, folder, live-verify guards)" \
          bash -c "cd .. && python observability/grafana/verify_provisioning.py && \
                   python observability/grafana/verify_provisioning_test.py"
run_suite "agent sandbox (buyer job can't harm the seller host)" \
          bash -c "cd ../lumaris_agent && python sandbox_test.py"
run_suite "tunnel (nat + failover)" bash -c "cd ../lumaris_gateway && python tunnel_test.py"
rm -f smoke.db* adv.db* stripe_test.db* payout_test.db* seller_payable_metric_test.db* \
      reservation_reclaim_test.db* backup_test.db* security.db* ../lumaris_gateway/tunnel.db*

# Informational: honest seller-payout country coverage. This deliberately reports a
# SHORTFALL (0/100) today and is NOT a gate — coverage grows only through real provider
# approvals + implemented rails, never by editing the dataset. Printed so the number
# stays visible on every run; its non-zero exit is swallowed on purpose.
echo ""
echo "${BOLD}--- seller-payout country coverage (informational) ---${OFF}"
set +e
python ../scripts/verify_payout_country_coverage.py
_cov=$?
set -e
if [[ $_cov -eq 0 || $_cov -eq 1 ]]; then
  echo "coverage check exit=$_cov (0=target met, 1=expected honest shortfall)"
else
  echo "${RED}coverage VERIFIER ERROR (exit=$_cov) — malformed dataset / regression${OFF}"
  fail=1
fi

# ---------------------------------------------------------------- Postgres
if [[ "${1:-}" == "--postgres" ]]; then
  echo ""
  echo "${BOLD}=========== PostgreSQL (the one that counts) ===========${OFF}"

  PGBIN=${PGBIN:-/usr/lib/postgresql/16/bin}
  PGPORT=${PGPORT:-5433}
  PGDATA=${PGDATA:-/tmp/pgdata-petabyte}
  export DATABASE_URL="postgresql+psycopg2://postgres@127.0.0.1:${PGPORT}/petabyte_test"

  if ! pg_isready -h 127.0.0.1 -p "$PGPORT" >/dev/null 2>&1; then
    echo "starting a throwaway postgres on :$PGPORT ..."
    rm -rf "$PGDATA"; mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA" 2>/dev/null || true
    su postgres -c "$PGBIN/initdb -D $PGDATA -U postgres --auth=trust" >/dev/null 2>&1
    su postgres -c "$PGBIN/pg_ctl -D $PGDATA -o '-p $PGPORT -k /tmp -c listen_addresses=127.0.0.1' -l /tmp/pg.log start" >/dev/null 2>&1
    sleep 3
    su postgres -c "$PGBIN/psql -h 127.0.0.1 -p $PGPORT -U postgres -c 'CREATE DATABASE petabyte_test;'" >/dev/null 2>&1 || true
  fi

  run_suite "smoke (postgres)"       python smoke_test.py
  run_suite "adversarial (postgres)" python adversarial_test.py
  run_suite "stripe connect (postgres)" python stripe_test.py
  run_suite "payout routing (postgres)" python payout_test.py
  run_suite "postgres-only invariants (exact NUMERIC, advisory lock, real races)" \
            python postgres_test.py
else
  echo ""
  echo "${BOLD}NOTE:${OFF} skipped Postgres. Re-run with ${BOLD}--postgres${OFF} before you"
  echo "      trust anything about money or concurrency. SQLite cannot see those bugs."
fi

echo ""
if [[ $fail -eq 0 ]]; then
  echo "${GREEN}${BOLD}all suites passed${OFF}"
else
  echo "${RED}${BOLD}SOME SUITES FAILED${OFF}"
fi
exit $fail
