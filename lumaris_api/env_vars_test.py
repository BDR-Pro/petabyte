"""Tests for the single-variable ENV_VARS configuration model: the parser, the
secret-guard, precedence, generated-env content/permissions, and that no existing safety
validation is weakened. No DB/app needed.

Run: python env_vars_test.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import yaml  # noqa: E402
import env_vars as ev  # noqa: E402
import generate_deploy_env as G  # noqa: E402

MANIFEST = yaml.safe_load(open(os.path.join(ROOT, "config", "github_configuration_manifest.yaml")))
VAL = os.path.join(ROOT, "scripts", "validate_github_configuration.py")

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---- parser: basic semicolon + whitespace + blanks ----
v, e = ev.parse_bundle("ENVIRONMENT=production; LOG_LEVEL=INFO ;\n BASE_DOMAIN=petabyte.market;\n")
ok("semicolon split + trim + ignore blanks", e == [] and v == {
    "ENVIRONMENT": "production", "LOG_LEVEL": "INFO", "BASE_DOMAIN": "petabyte.market"})

# ---- multiline bundle (newlines are just formatting) ----
v, e = ev.parse_bundle("A_ONE=1;\nA_TWO=2;\n\nA_THREE=3;\n")
ok("multiline bundle parses", e == [] and v == {"A_ONE": "1", "A_TWO": "2", "A_THREE": "3"})

# ---- value containing '=' (split on FIRST '=' only) ----
v, e = ev.parse_bundle("DATABASE_OPTIONS=sslmode=require;")
ok("value with '=' preserved (split on first '=')",
   e == [] and v == {"DATABASE_OPTIONS": "sslmode=require"})

# ---- URL with query params (multiple '=' and '&') ----
v, e = ev.parse_bundle("PUBLIC_BASE_URL=https://petabyte.market/cb?a=1&b=2;")
ok("URL with query params preserved",
   v.get("PUBLIC_BASE_URL") == "https://petabyte.market/cb?a=1&b=2")

# ---- empty value allowed ----
v, e = ev.parse_bundle("ALLOWED_ORIGINS=;")
ok("empty value is allowed", e == [] and v == {"ALLOWED_ORIGINS": ""})

# ---- duplicate keys fail ----
v, e = ev.parse_bundle("LOG_LEVEL=INFO; LOG_LEVEL=DEBUG;")
ok("duplicate key rejected", any("duplicate key: LOG_LEVEL" in x for x in e))

# ---- malformed keys fail ----
for bad in ("log_level=x;", "1BAD=x;", "BAD-KEY=x;", "BAD KEY=x;"):
    _, e = ev.parse_bundle(bad)
    ok(f"malformed key rejected ({bad.split('=')[0]})", any("invalid variable name" in x for x in e))

# ---- entry without '=' rejected ----
_, e = ev.parse_bundle("JUSTAKEY;")
ok("entry without '=' rejected", any("without '='" in x for x in e))

# ---- null byte rejected ----
_, e = ev.parse_bundle("A=b;\x00")
ok("null byte rejected", any("null byte" in x for x in e))

# ---- newline injection into a value rejected ----
_, e = ev.parse_bundle("A=line1\nline2")   # no ';' between -> one entry with inner newline
ok("newline-injected value rejected", any("newline" in x.lower() for x in e))

# ---- malicious shell syntax kept as LITERAL DATA (not executed, not rejected) ----
v, e = ev.parse_bundle("EVIL_ONE=$(rm -rf /); EVIL_TWO=`whoami`; EVIL_THREE=a && b | c;")
ok("shell substitution kept literal",
   v.get("EVIL_ONE") == "$(rm -rf /)" and v.get("EVIL_TWO") == "`whoami`")
ok("shell operators kept literal", v.get("EVIL_THREE") == "a && b | c" and e == [])

# ---- 100+ variables ----
big = "".join(f"VAR_{i}=v{i};\n" for i in range(150))
v, e = ev.parse_bundle(big)
ok("100+ variables parse", e == [] and len(v) == 150 and v["VAR_149"] == "v149")

# ---- secret inside ENV_VARS rejected, sanitized (value NEVER echoed) ----
v, _ = ev.parse_bundle("LOG_LEVEL=INFO; STRIPE_SECRET_KEY=sk_test_LEAKME;")
errs = ev.check_no_secrets(v, MANIFEST)
ok("secret in ENV_VARS rejected", any("STRIPE_SECRET_KEY is classified as a GitHub Secret" in x for x in errs))
ok("secret VALUE never appears in the error", not any("sk_test_LEAKME" in x for x in errs))
# denylist defense in depth: an undocumented *_PASSWORD is still refused
ok("denylist refuses an undocumented *_PASSWORD",
   ev.is_secret_name("SOME_NEW_PASSWORD", MANIFEST))

# ---- unknown keys reported ----
v, _ = ev.parse_bundle("TOTALLY_MADE_UP=1; LOG_LEVEL=INFO;")
ok("unknown key reported", any("TOTALLY_MADE_UP" in x for x in ev.check_known(v, MANIFEST)))
ok("known key not reported as unknown",
   not any("LOG_LEVEL" in x for x in ev.check_known(v, MANIFEST)))

# ---- legacy individual variables detected ----
legacy = ev.detect_legacy_individual_vars(
    {"ENV_VARS": "...", "DEPLOY_CONFIG_FROM_GITHUB": "true", "LOG_LEVEL": "INFO",
     "STRIPE_MODE": "test"}, MANIFEST)
ok("legacy individual vars detected", set(legacy) == {"LOG_LEVEL", "STRIPE_MODE"})
ok("bootstrap vars are not flagged as legacy",
   "ENV_VARS" not in legacy and "DEPLOY_CONFIG_FROM_GITHUB" not in legacy)


def _run_validator(env_overrides, env_name="test"):
    env = {k: v for k, v in os.environ.items()
           if k not in {"VARS_JSON", "SECRETS_JSON", "ENV_VARS"}}
    env.update(env_overrides)
    p = subprocess.run([sys.executable, VAL, "--env-name", env_name],
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


import json  # noqa: E402
_SECRETS = json.dumps({
    "SECRET_KEY": "x" * 40, "SERVER_PRIVATE_KEY": "fk", "DATABASE_URL": "postgresql://u:p@h/db",
    "DEPLOY_SSH_KEY": "k", "DROPLET_HOST": "1.2.3.4", "DROPLET_USER": "deploy",
    "DROPLET_SSH_KNOWN_HOSTS": "1.2.3.4 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA"})

# ---- validator: a valid test bundle passes ----
rc, out = _run_validator({
    "ENV_VARS": "ENVIRONMENT=test; STRIPE_MODE=test; PAYMENTS_LIVE_ENABLED=false; LOG_LEVEL=INFO;",
    "SECRETS_JSON": _SECRETS})
ok("validator: valid test bundle passes", rc == 0)

# ---- validator: a secret inside ENV_VARS fails, value not printed ----
rc, out = _run_validator({
    "ENV_VARS": "LOG_LEVEL=INFO; STRIPE_SECRET_KEY=sk_test_SHOULDNOTPRINT;",
    "SECRETS_JSON": _SECRETS})
ok("validator: secret in ENV_VARS fails", rc == 1 and "classified as a GitHub Secret" in out)
ok("validator: secret value not printed", "sk_test_SHOULDNOTPRINT" not in out)

# ---- validator: legacy individual var alongside ENV_VARS fails (no silent mixing) ----
rc, out = _run_validator({
    "ENV_VARS": "LOG_LEVEL=INFO;",
    "VARS_JSON": json.dumps({"ENV_VARS": "LOG_LEVEL=INFO;", "STRIPE_MODE": "test"}),
    "SECRETS_JSON": _SECRETS})
ok("validator: legacy individual var detected + fails",
   rc == 1 and "Legacy individual GitHub Variables" in out and "STRIPE_MODE" in out)

# ---- validator: unknown key in bundle fails ----
rc, out = _run_validator({"ENV_VARS": "MADE_UP_KEY=1; LOG_LEVEL=INFO;", "SECRETS_JSON": _SECRETS})
ok("validator: unknown key fails", rc == 1 and "MADE_UP_KEY" in out)

# ---- validator: safety rules still apply — live key in test bundle rejected ----
rc, out = _run_validator({
    "ENV_VARS": "STRIPE_MODE=test; PAYMENTS_LIVE_ENABLED=false;",
    "SECRETS_JSON": json.dumps({**json.loads(_SECRETS), "STRIPE_SECRET_KEY": "sk_live_X"})})
ok("validator: test/live separation still enforced (live key in test)",
   rc == 1 and ("LIVE Stripe key" in out or "test key" in out))

# ---- validator: production live bundle passes ----
rc, out = _run_validator({
    "ENV_VARS": ("ENVIRONMENT=production; STRIPE_MODE=live; PAYMENTS_LIVE_ENABLED=true; "
                 "STRIPE_ALLOW_LIVE=true; STRIPE_GATEWAY=real; GOOGLE_OAUTH_STUB=false; "
                 "PAYOUT_STUB=false; NOTIFY_STUB=false; S3_STUB=false; "
                 "OTEL_EXPORTER_OTLP_ENDPOINT=http://obs:4317; OBSERVABILITY_REQUIRED=true; "
                 "PUBLIC_BASE_URL=https://petabyte.market; "
                 "GOOGLE_REDIRECT_URI=https://petabyte.market/cb;"),
    "SECRETS_JSON": json.dumps({**json.loads(_SECRETS),
                                "STRIPE_SECRET_KEY": "sk_live_X",
                                "STRIPE_PUBLISHABLE_KEY": "pk_live_X",
                                "STRIPE_WEBHOOK_SECRET": "whsec_X"})},
    env_name="production")
ok("validator: production+live bundle passes", rc == 0)

# ---- precedence + defaults: ENV_VARS overrides default; unset -> default ----
import config_context as cc  # noqa: E402
for k in ("ENV_VARS", "VARS_JSON", "SECRETS_JSON", "LOG_LEVEL", "PAYOUT_HOLD_DAYS"):
    os.environ.pop(k, None)
os.environ["ENV_VARS"] = "LOG_LEVEL=DEBUG;"
os.environ["SECRETS_JSON"] = _SECRETS
cc.hydrate_env()
import validate_github_configuration as V  # noqa: E402
resolved, secret_status, _ = V.resolve(MANIFEST, dict(os.environ), {"platform", "deployment"})
ok("ENV_VARS overrides the manifest default (LOG_LEVEL=DEBUG)", resolved.get("LOG_LEVEL") == "DEBUG")
ok("unset var falls back to its default (PAYOUT_HOLD_DAYS=14)", resolved.get("PAYOUT_HOLD_DAYS") == "14")
ok("secret still resolved from SECRETS_JSON (precedence)", secret_status.get("SECRET_KEY") is True)

# ---- generated platform .env: content from the bundle + 0600 perms ----
gen = "/tmp/env_vars_test.platform.generated"
if os.path.exists(gen):
    os.remove(gen)
G.main(["--target", "platform", "--out", gen])
body = open(gen).read()
import stat
mode = stat.S_IMODE(os.stat(gen).st_mode)
ok("generated platform env is 0600", mode == 0o600)
ok("generated env carries the ENV_VARS value (LOG_LEVEL=DEBUG)", "LOG_LEVEL=DEBUG" in body)
ok("generated env carries a required secret (DATABASE_URL)", "DATABASE_URL=" in body)
os.remove(gen)

# ---- GPU env still excludes platform secrets (scope separation unchanged) ----
gpu = "/tmp/env_vars_test.gpu.generated"
os.environ["PETABYTE_API_KEY"] = "nodekey"; os.environ["PETABYTE_API_URL"] = "https://petabyte.market"
os.environ["PETABYTE_SPEC_ID"] = "1"
if os.path.exists(gpu):
    os.remove(gpu)
G.main(["--target", "gpu", "--out", gpu])
gbody = open(gpu).read()
ok("GPU env excludes platform secrets (DATABASE_URL/STRIPE)",
   "DATABASE_URL" not in gbody and "STRIPE" not in gbody and "SECRET_KEY" not in gbody)
os.remove(gpu)

# ---- drift detection still passes ----
drift = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "check_configuration_drift.py")],
                       capture_output=True, text=True)
ok("configuration drift check still passes", drift.returncode == 0)

print(f"\n=== env_vars: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
