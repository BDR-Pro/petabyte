#!/usr/bin/env python3
"""Validate the deployment configuration resolved from GitHub Variables + Secrets.

This is the single gate that runs BEFORE tests, builds, and deploy (the
`configuration-preflight` job). It reads config/github_configuration_manifest.yaml, takes
the resolved values from the process environment (GitHub Actions injects
`${{ vars.* }}` and `${{ secrets.* }}` as env vars), then:

  * applies documented defaults for any missing non-sensitive Variable,
  * validates every value's format (bool / int / float / url / hostname / email / one-of),
  * enforces environment-specific rules (test vs staging vs production),
  * enforces Stripe test/live separation (a live key can never be used in test mode, and
    test defaults can never silently start a production/live deploy),
  * fails closed when a REQUIRED Secret is missing,
  * reports unknown / obsolete env vars,
  * prints a SANITISED summary (secrets shown as `NAME=SET`, never their value).

It exits non-zero on any error so CI stops before anything is built or deployed.

Usage:
    python scripts/validate_github_configuration.py --env-name production
    python scripts/validate_github_configuration.py --env-name test --github-env "$GITHUB_ENV"

Secret values are NEVER printed. Only presence (`SET`) is ever reported.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is in requirements
    print("::error::PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST = os.path.join(ROOT, "config", "github_configuration_manifest.yaml")

# Env vars that are legitimately present in a CI/runner environment but are NOT deployment
# configuration — never flag these as "unknown".
_RUNNER_NOISE = re.compile(
    r"^(GITHUB_|RUNNER_|ACTIONS_|CI$|HOME$|PATH$|PWD$|SHELL$|USER$|LANG$|LC_|TERM$|"
    r"HOSTNAME$|_$|PYTHON|PIP_|VIRTUAL_ENV$|LD_|TZ$|EDITOR$|SHLVL$|OLDPWD$|"
    r"HTTPS?_PROXY$|NO_PROXY$|http_proxy$|https_proxy$|no_proxy$)"
)


class Result:
    """Accumulates errors (fail the build) and warnings (surface, don't fail)."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---- format validators -----------------------------------------------------------------
_BOOL = {"true", "false"}


def _is_bool(v: str) -> bool:
    return v.lower() in _BOOL


def _is_int(v: str) -> bool:
    try:
        int(v)
        return True
    except ValueError:
        return False


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


def _is_url(v: str) -> bool:
    return bool(re.match(r"^https?://[^\s/$.?#].[^\s]*$", v)) or v.startswith(
        ("postgresql", "postgres", "sqlite", "mysql", "redis")
    )


def _is_https(v: str) -> bool:
    return v.startswith("https://")


def _is_hostname(v: str) -> bool:
    return bool(re.match(r"^(?=.{1,253}$)([a-zA-Z0-9-]{1,63}\.)+[a-zA-Z]{2,63}$", v))


def _is_email(v: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v))


def _validate_format(name: str, value: str, fmt: str, res: Result) -> None:
    if value == "":
        # empties are handled by required/optional logic; a blank optional is fine.
        if fmt.endswith("_or_empty"):
            return
        return
    base = fmt[: -len("_or_empty")] if fmt.endswith("_or_empty") else fmt
    checks = {
        "bool": (_is_bool, "must be 'true' or 'false'"),
        "int": (_is_int, "must be an integer"),
        "float": (_is_float, "must be a number"),
        "url": (_is_url, "must be a URL"),
        "https": (_is_https, "must be an https:// URL"),
        "hostname": (_is_hostname, "must be a bare hostname (e.g. petabyte.market)"),
        "email": (_is_email, "must be an email address"),
        "csv": (lambda v: True, ""),
    }
    check = checks.get(base)
    if check and not check[0](value):
        res.error(f"{name} {check[1]} (got: {_preview(value)})")


def _preview(value: str, n: int = 24) -> str:
    """A short, safe preview of a NON-secret value for error messages."""
    value = value.replace("\n", "\\n")
    return value if len(value) <= n else value[:n] + "…"


# ---- resolution ------------------------------------------------------------------------
def _get_env(env: dict, name: str, aka: str | None) -> str | None:
    """Return the first NON-EMPTY value for a canonical name or its documented `aka` alias.

    An explicitly-empty variable is treated as unset, so it predictably falls back to the
    documented default (a blank in the GitHub UI never silently overrides a safe default
    with an empty string).
    """
    for key in (name, aka):
        if key and env.get(key, "") != "":
            return env[key]
    return None


def _in_scope(meta: dict, scopes: set | None) -> bool:
    """True if this entry belongs to any of the requested scopes (None = all scopes)."""
    if scopes is None:
        return True
    return bool(set(meta.get("scope", [])) & scopes)


def resolve(manifest: dict, env: dict, scopes: set | None = None):
    """Resolve variables (defaults applied) + record which secrets are present.

    `scopes` (e.g. {"platform","deployment"}) limits which manifest entries are required
    and reported — the platform preflight must not demand GPU-node vars, and vice versa.

    Returns (resolved_vars, secret_status, result) where resolved_vars maps every in-scope
    non-secret variable name to its effective value, and secret_status maps every in-scope
    secret name to a bool (present & non-empty).
    """
    res = Result()
    variables = manifest.get("variables", {})
    secrets = manifest.get("secrets", {})

    resolved: dict[str, str] = {}
    for name, meta in variables.items():
        if not _in_scope(meta, scopes):
            continue
        aka = meta.get("aka")
        val = _get_env(env, name, aka)
        if val is None:
            default = meta.get("default")
            if meta.get("required") and default is None:
                res.error(f"Missing required Variable: {name}"
                          + (f" (or {aka})" if aka else ""))
                continue
            val = "" if default is None else str(default)
        resolved[name] = val
        # format + allowed-value validation
        fmt = meta.get("format")
        if fmt:
            _validate_format(name, val, fmt, res)
        allowed = meta.get("allowed")
        if allowed and val != "" and val not in allowed:
            res.error(f"{name} must be one of {allowed} (got: {_preview(val)})")

    secret_status: dict[str, bool] = {}
    for name, meta in secrets.items():
        if not _in_scope(meta, scopes):
            continue
        aka = meta.get("aka")
        val = _get_env(env, name, aka)
        present = bool(val)
        secret_status[name] = present
        if meta.get("required") and not present:
            res.error(f"Missing required Secret: {name}"
                      + (f" (or {aka})" if aka else "")
                      + " — set it in GitHub → Settings → Secrets.")

    return resolved, secret_status, res


# ---- cross-field / environment-specific rules ------------------------------------------
def _rget(resolved: dict, name: str, default: str = "") -> str:
    return (resolved.get(name) or default).strip()


def enforce_rules(resolved: dict, secret_status: dict, env: dict, env_name: str,
                  res: Result) -> None:
    """Environment-specific + Stripe test/live separation rules. Fail closed."""
    env_name = (env_name or "").lower()
    app_env = _rget(resolved, "ENVIRONMENT").lower()
    stripe_mode = _rget(resolved, "STRIPE_MODE").lower()
    live_enabled = _rget(resolved, "PAYMENTS_LIVE_ENABLED").lower() == "true"
    allow_live = _rget(resolved, "STRIPE_ALLOW_LIVE").lower() == "true"

    # Stripe key/mode consistency (values from env; keys are secrets — check PREFIX only,
    # never echo the key). A prefix is not the secret; it only reveals test-vs-live.
    sk = env.get("STRIPE_SECRET_KEY", "") or ""
    pk = env.get("STRIPE_PUBLISHABLE_KEY", "") or ""
    sk_live = sk.startswith(("sk_live_", "rk_live_"))
    sk_test = sk.startswith("sk_test_")
    pk_live = pk.startswith("pk_live_")
    pk_test = pk.startswith("pk_test_")

    # --- universal test/live separation ---
    if stripe_mode == "test" or (not live_enabled):
        if sk_live or pk_live:
            res.error("Stripe test mode / PAYMENTS_LIVE_ENABLED=false but a LIVE Stripe key "
                      "is set. Test and live keys must never be mixed.")
    if stripe_mode == "live" or live_enabled:
        if sk and not sk_live:
            res.error("Stripe live mode but STRIPE_SECRET_KEY is not a live key (sk_live_/rk_live_).")
        if pk and not pk_live:
            res.error("Stripe live mode but STRIPE_PUBLISHABLE_KEY is not a live key (pk_live_).")
    # declared-vs-actual mode mismatch
    if stripe_mode == "test" and (sk_live or pk_live):
        res.error("STRIPE_MODE=test contradicts the live key prefixes.")
    if stripe_mode == "live" and (sk_test or pk_test):
        res.error("STRIPE_MODE=live contradicts the test key prefixes.")

    # --- TEST / STAGING environment ---
    if env_name in ("test", "staging"):
        if stripe_mode and stripe_mode != "test":
            res.error(f"{env_name}: STRIPE_MODE must be 'test' (got '{stripe_mode}').")
        if live_enabled:
            res.error(f"{env_name}: PAYMENTS_LIVE_ENABLED must be false.")
        if sk and not sk_test:
            res.error(f"{env_name}: STRIPE_SECRET_KEY must be a test key (sk_test_).")
        if pk and not pk_test:
            res.error(f"{env_name}: STRIPE_PUBLISHABLE_KEY must be a test key (pk_test_).")

    # --- PRODUCTION environment ---
    if env_name == "production":
        if app_env != "production":
            res.error("production: ENVIRONMENT (APP_ENV) must be 'production' — the app "
                      "refuses to boot with stubs otherwise, but do not rely on that alone.")
        # stubs / escape hatches must be off
        for stub, why in (("GOOGLE_OAUTH_STUB", "open demo login"),
                          ("PAYOUT_STUB", "payouts would be simulated"),
                          ("NOTIFY_STUB", "emails would not send"),
                          ("S3_STUB", "backups would be simulated"),
                          ("LEGACY_KEYS_FULL_ACCESS", "scopeless keys act as root")):
            if _rget(resolved, stub).lower() == "true":
                res.error(f"production: {stub}=true is unsafe ({why}). Must be false.")
        # CORS must not be a wildcard
        if _rget(resolved, "ALLOWED_ORIGINS") == "*":
            res.error("production: ALLOWED_ORIGINS='*' is forbidden — list explicit origins.")
        # public URLs must be https
        for u in ("PUBLIC_BASE_URL", "GOOGLE_REDIRECT_URI"):
            v = _rget(resolved, u)
            if v and not v.startswith("https://"):
                res.error(f"production: {u} must be an https:// URL (got: {_preview(v)}).")
        # bind must stay loopback (behind nginx), never public
        bind = _rget(resolved, "BIND")
        if bind and not (bind.startswith("127.0.0.1") or bind.startswith("localhost")):
            res.warn(f"production: BIND={bind} is not loopback — ensure it is not publicly exposed.")
        # a bounded job runtime + upload size must be set (no 'unlimited' in prod)
        for bound in ("PLATFORM_MAX_DURATION_S",):
            v = _rget(resolved, bound)
            if not v or (v.isdigit() and int(v) <= 0):
                res.error(f"production: {bound} must be a positive bound (no unlimited runtime).")
        # if going live, every live prerequisite must hold together
        if live_enabled:
            if stripe_mode != "live":
                res.error("production+live: STRIPE_MODE must be 'live'.")
            if not allow_live:
                res.error("production+live: STRIPE_ALLOW_LIVE must be true.")
            if _rget(resolved, "STRIPE_GATEWAY") != "real":
                res.error("production+live: STRIPE_GATEWAY must be 'real' (no half-live).")
            if not sk_live:
                res.error("production+live: a live STRIPE_SECRET_KEY (sk_live_) is required.")
            if not secret_status.get("STRIPE_WEBHOOK_SECRET"):
                res.error("production+live: STRIPE_WEBHOOK_SECRET is required.")
        else:
            res.error("production requires PAYMENTS_LIVE_ENABLED=true — a live production "
                      "deploy must not run on test-credit defaults. Use --env-name staging "
                      "for production-grade infra that is still on test money.")
        # required strong secrets must be present (fail closed)
        for s in ("SECRET_KEY", "SERVER_PRIVATE_KEY", "DATABASE_URL"):
            if not secret_status.get(s):
                res.error(f"production: required Secret {s} is missing.")


def enforce_observability(resolved: dict, secret_status: dict, env_name: str,
                          res: Result) -> None:
    """Observability preflight. Telemetry is degrade-safe at runtime, but production and
    investor-demo deployments must not SILENTLY run with observability off/unconfigured.
    Controlled by OBSERVABILITY_REQUIRED (default: required in production)."""
    env_name = (env_name or "").lower()
    obs_enabled = _rget(resolved, "OBSERVABILITY_ENABLED", "true").lower() == "true"
    required = _rget(resolved, "OBSERVABILITY_REQUIRED",
                     "true" if env_name == "production" else "false").lower() == "true"
    # log redaction must never be off in production
    if env_name == "production" and _rget(resolved, "LOG_REDACTION_ENABLED", "true").lower() == "false":
        res.error("production: LOG_REDACTION_ENABLED must be true (no unredacted logs).")
    if _rget(resolved, "LOG_FORMAT", "json").lower() != "json" and env_name == "production":
        res.warn("production: LOG_FORMAT is not json — structured logging is expected.")
    if not required:
        if not obs_enabled:
            res.warn("OBSERVABILITY_ENABLED=false — telemetry is OFF (allowed here).")
        return
    # required: fail closed on the essentials
    if not obs_enabled:
        res.error(f"{env_name}: OBSERVABILITY_ENABLED must be true (set OBSERVABILITY_REQUIRED"
                  "=false only for approved environments).")
    if _rget(resolved, "OTEL_ENABLED", "true").lower() == "true" \
            and not _rget(resolved, "OTEL_EXPORTER_OTLP_ENDPOINT"):
        res.error(f"{env_name}: OTEL_ENABLED but OTEL_EXPORTER_OTLP_ENDPOINT is unset — "
                  "traces would silently not reach Tempo.")
    if _rget(resolved, "OBSERVABILITY_FAILURE_MODE", "degrade").lower() not in ("degrade", "strict"):
        res.error("OBSERVABILITY_FAILURE_MODE must be 'degrade' or 'strict'.")


# ---- unknown / obsolete detection ------------------------------------------------------
def find_unknown(manifest: dict, env: dict, res: Result) -> list[str]:
    known = set(manifest.get("variables", {})) | set(manifest.get("secrets", {}))
    for meta in list(manifest.get("variables", {}).values()) + list(manifest.get("secrets", {}).values()):
        if meta.get("aka"):
            known.add(meta["aka"])
    unknown = []
    for name in env:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]+", name):
            continue
        if name in known or _RUNNER_NOISE.match(name):
            continue
        unknown.append(name)
    for name in sorted(unknown):
        res.warn(f"Unknown/undocumented env var present: {name} "
                 "(add it to the manifest or remove it).")
    return sorted(unknown)


# ---- summary ---------------------------------------------------------------------------
def print_summary(resolved: dict, secret_status: dict, env_name: str) -> None:
    print(f"\n=== configuration summary (env: {env_name or 'unspecified'}) ===")
    print("-- Variables (resolved; defaults applied) --")
    for name in sorted(resolved):
        val = resolved[name]
        shown = val if val != "" else "(empty)"
        print(f"  {name}={shown}")
    print("-- Secrets (presence only; values never shown) --")
    for name in sorted(secret_status):
        print(f"  {name}={'SET' if secret_status[name] else 'MISSING'}")


def _export_github_env(resolved: dict, path: str) -> None:
    """Append resolved NON-SECRET variables to $GITHUB_ENV for later workflow steps."""
    with open(path, "a") as f:
        for name, val in sorted(resolved.items()):
            f.write(f"{name}={val}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--env-name", default=os.getenv("CONFIG_ENV_NAME", ""),
                    help="test | staging | production (drives environment-specific rules).")
    ap.add_argument("--scope", default="platform,deployment",
                    help="Comma list of scopes to validate (platform,deployment,gpu). "
                         "Default is a platform deploy; use 'gpu' for a GPU-node check, "
                         "or 'all' for everything.")
    ap.add_argument("--github-env", default="",
                    help="Path to $GITHUB_ENV; if given, resolved non-secret vars are exported.")
    ap.add_argument("--strict-unknown", action="store_true",
                    help="Treat unknown/undocumented env vars as errors, not warnings.")
    args = ap.parse_args(argv)

    from config_context import hydrate_env
    hydrate_env()  # merge GitHub vars/secrets JSON into the env, if the workflow passed them

    with open(args.manifest) as f:
        manifest = yaml.safe_load(f)

    scopes = None if args.scope.strip().lower() == "all" else {
        s.strip() for s in args.scope.split(",") if s.strip()}

    env = dict(os.environ)
    resolved, secret_status, res = resolve(manifest, env, scopes)
    enforce_rules(resolved, secret_status, env, args.env_name, res)
    enforce_observability(resolved, secret_status, args.env_name, res)
    unknown = find_unknown(manifest, env, res)
    if args.strict_unknown and unknown:
        for u in unknown:
            res.error(f"Unknown/undocumented env var: {u}")

    print_summary(resolved, secret_status, args.env_name)

    if res.warnings:
        print("\n-- warnings --")
        for w in res.warnings:
            print(f"  ::warning::{w}")
    if res.errors:
        print("\n-- errors --")
        for e in res.errors:
            print(f"  ::error::{e}")
        print(f"\nFAILED: {len(res.errors)} configuration error(s).")
        return 1

    if args.github_env:
        _export_github_env(resolved, args.github_env)

    print("\nOK: configuration is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
