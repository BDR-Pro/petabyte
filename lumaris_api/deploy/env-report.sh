#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Environment health report. Reads /etc/lumaris/lumaris.env and prints, per
# integration, whether it is LIVE / STUB / SET / MISSING — so at a glance you
# can see what a deployment will really do, without reading the whole env file.
#
# Called at the end of every deploy (deploy.sh and update.sh). When it runs
# inside GitHub Actions it ALSO writes the report to the job's Step Summary,
# so you can read it on github.com without SSHing into the box.
#
# Run by hand anytime:  sudo bash /opt/lumaris/deploy/env-report.sh
# ---------------------------------------------------------------------------
ENVF="${LUMARIS_ENV_FILE:-/etc/lumaris/lumaris.env}"

_get() { grep -E "^$1=" "$ENVF" 2>/dev/null | head -1 | cut -d= -f2-; }

report() {
  echo ""
  echo "================ environment report ================"
  if [ ! -f "$ENVF" ]; then
    echo "  (no env file at $ENVF yet — nothing to report)"
    echo "===================================================="
    return
  fi
  _report() {  # name, kind: stubflag|secret|value, hint
    local name="$1" kind="$2" hint="$3" val; val="$(_get "$name")"
    case "$kind" in
      stubflag)
        if [ "$val" = "true" ]; then echo "  [STUB]    $name=true            ($hint)";
        else echo "  [LIVE]    $name=${val:-false}"; fi ;;
      secret)
        if [ -z "$val" ]; then echo "  [MISSING] $name                  ($hint)";
        else echo "  [SET]     $name=***"; fi ;;
      value)
        if [ -z "$val" ]; then echo "  [MISSING] $name                  ($hint)";
        else echo "  [DEFAULT] $name=$val"; fi ;;
    esac
  }
  echo "-- money --"
  local PM; PM="$(_get PAYMENTS_MODE)"
  if [ "$PM" = "live" ]; then echo "  [LIVE]    PAYMENTS_MODE=live";
  else echo "  [STUB]    PAYMENTS_MODE=${PM:-sandbox}   (deposits mint test credit; GMV excluded)"; fi
  _report PAYOUT_STUB stubflag "payouts simulated; no real money out"
  _report STRIPE_API_KEY secret "needed for PAYMENTS_MODE=live"
  echo "-- production safety --"
  local ENVV; ENVV="$(_get ENVIRONMENT)"
  if [ "$ENVV" = "production" ]; then echo "  [LIVE]    ENVIRONMENT=production   (boot gate armed: stubs will block startup)";
  else echo "  [DEV]     ENVIRONMENT=${ENVV:-development}   (flip to production once stubs are off)"; fi
  _report LEGACY_KEYS_FULL_ACCESS stubflag "DANGER if true in prod: scopeless keys = root"
  _report TRUSTED_PROXIES value "XFF trust list; keep tight (rate-limit + geo depend on it)"
  echo "-- identity / auth --"
  _report GOOGLE_OAUTH_STUB stubflag "DANGER if true in prod: open demo login"
  _report GOOGLE_CLIENT_ID secret "Google sign-in off without it"
  _report SECRET_KEY secret "JWT signing (rotate if ever leaked)"
  echo "-- infra --"
  _report S3_STUB stubflag "snapshots simulated; failover restores nothing real"
  _report S3_BUCKET secret "required when S3_STUB=false"
  _report SENTRY_DSN secret "no error tracking without it"
  _report GATEWAY_TOKEN secret "VM gateway route resolution off without it"
  _report BASE_DOMAIN value "stable VM URLs"
  echo "-- optional integrations --"
  _report NOTIFY_STUB stubflag "emails recorded, not sent"
  _report NICEHASH_STUB stubflag "idle-mining pricing simulated"
  _report GEOIP_STUB stubflag "region verification from env map"
  _report CAL_BOOKING_URL value "demo self-booking off until set to your Cal.com link"
  echo "===================================================="
  echo "Legend: [LIVE] real · [STUB] simulated (safe) · [SET] secret present"
  echo "        [DEFAULT] using default · [MISSING] unset — feature off or will fail"
  echo "Details: docs/stub.md · grep -rn 'TODO(stub)' for code sites"
}

# Print to the deploy log always.
report

# If we're inside GitHub Actions, also publish to the job's Step Summary so it's
# readable on github.com without SSH. Secrets are already masked (shown as ***).
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## Deploy environment report"
    echo '```'
    report
    echo '```'
  } >> "$GITHUB_STEP_SUMMARY"
fi
