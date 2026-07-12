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
run_suite "tunnel (nat + failover)" bash -c "cd ../lumaris_gateway && python tunnel_test.py"
rm -f smoke.db* adv.db* ../lumaris_gateway/tunnel.db*

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
