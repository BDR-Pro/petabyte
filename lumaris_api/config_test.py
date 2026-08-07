"""Offline tests for the GitHub-config-source-of-truth toolchain:
manifest + validator + deploy-env generator + drift + docs.

Covers: defaults applied, override wins, empty is predictable, invalid bool/url/int fail,
missing required secret fails closed, secrets are never printed, Stripe test/live
separation both ways, production requires live + test rejects live, the GPU node env never
receives platform secrets, generated files are git-ignored, and undocumented vars are
reported. No app/DB needed — these drive the config scripts directly.

Run: python config_test.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import yaml  # noqa: E402
import validate_github_configuration as V  # noqa: E402
import generate_deploy_env as G  # noqa: E402

MANIFEST = os.path.join(ROOT, "config", "github_configuration_manifest.yaml")
with open(MANIFEST) as f:
    M = yaml.safe_load(f)

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _base_platform_env(**over):
    """A minimal, valid platform env (required secrets present) to layer overrides on."""
    env = {
        "SECRET_KEY": "a-long-enough-secret-key-000000000000",
        "SERVER_PRIVATE_KEY": "fernet-key-placeholder",
        "DATABASE_URL": "postgresql+psycopg2://u:p@h:5432/db",
        "DEPLOY_SSH_KEY": "ssh-key", "DROPLET_HOST": "1.2.3.4", "DROPLET_USER": "deploy",
    }
    env.update(over)
    return env


PLAT = {"platform", "deployment"}

# ---- defaults / override / empty ----
res_env = _base_platform_env()
resolved, secrets, r = V.resolve(M, res_env, PLAT)
ok("missing optional var falls back to its documented default (PAYOUT_HOLD_DAYS=14)",
   resolved.get("PAYOUT_HOLD_DAYS") == "14")

resolved2, _, _ = V.resolve(M, _base_platform_env(PAYOUT_HOLD_DAYS="30"), PLAT)
ok("an explicit value overrides the default (PAYOUT_HOLD_DAYS=30)",
   resolved2.get("PAYOUT_HOLD_DAYS") == "30")

resolved3, _, _ = V.resolve(M, _base_platform_env(PAYOUT_HOLD_DAYS=""), PLAT)
ok("an empty variable is predictable — it falls back to the default, not ''",
   resolved3.get("PAYOUT_HOLD_DAYS") == "14")

# aka alias resolves the canonical name
resolvedA, _, _ = V.resolve(M, _base_platform_env(APP_ENV="staging"), PLAT)
ok("an aka alias resolves the canonical var (APP_ENV -> ENVIRONMENT)",
   resolvedA.get("ENVIRONMENT") == "staging")

# ---- invalid formats fail ----
_, _, rb = V.resolve(M, _base_platform_env(AUTO_SETTLE_ON_RESULT="maybe"), PLAT)
ok("invalid bool is rejected", any("AUTO_SETTLE_ON_RESULT" in e for e in rb.errors))

_, _, ri = V.resolve(M, _base_platform_env(HEARTBEAT_TIMEOUT_S="abc"), PLAT)
ok("invalid int is rejected", any("HEARTBEAT_TIMEOUT_S" in e for e in ri.errors))

_, _, ru = V.resolve(M, _base_platform_env(GOOGLE_REDIRECT_URI="not-a-url"), PLAT)
ok("invalid url is rejected", any("GOOGLE_REDIRECT_URI" in e for e in ru.errors))

_, _, rall = V.resolve(M, _base_platform_env(LOG_LEVEL="chatty"), PLAT)
ok("value outside the allowed set is rejected (LOG_LEVEL)",
   any("LOG_LEVEL" in e for e in rall.errors))

# ---- missing required secret fails closed ----
noS = _base_platform_env()
del noS["SECRET_KEY"]
_, _, rs = V.resolve(M, noS, PLAT)
ok("missing required secret fails closed (SECRET_KEY)",
   any("Missing required Secret: SECRET_KEY" in e for e in rs.errors))

# ---- Stripe test/live separation (both directions) ----
_, _, rtl = V.resolve(M, _base_platform_env(), PLAT)
V.enforce_rules(*V.resolve(M, _base_platform_env(
    STRIPE_MODE="test", PAYMENTS_LIVE_ENABLED="false",
    STRIPE_SECRET_KEY="sk_live_DEADBEEF"), PLAT)[:2],
    _base_platform_env(STRIPE_MODE="test", PAYMENTS_LIVE_ENABLED="false",
                       STRIPE_SECRET_KEY="sk_live_DEADBEEF"), "test", rtl)
ok("test mode rejects a LIVE Stripe key",
   any("LIVE Stripe key" in e or "test key" in e for e in rtl.errors))

rlt = V.Result()
liveenv = _base_platform_env(STRIPE_MODE="live", PAYMENTS_LIVE_ENABLED="true",
                             STRIPE_SECRET_KEY="sk_test_abc")
V.enforce_rules(*V.resolve(M, liveenv, PLAT)[:2], liveenv, "production", rlt)
ok("live mode rejects a TEST Stripe key",
   any("not a live key" in e or "contradicts the test key" in e for e in rlt.errors))

# ---- environment-specific: prod requires live; test rejects live ----
rprod = V.Result()
prodenv = _base_platform_env(ENVIRONMENT="production", APP_ENV="production",
                             STRIPE_MODE="test", PAYMENTS_LIVE_ENABLED="false",
                             GOOGLE_OAUTH_STUB="false", PAYOUT_STUB="false",
                             NOTIFY_STUB="false", S3_STUB="false",
                             PUBLIC_BASE_URL="https://petabyte.market")
V.enforce_rules(*V.resolve(M, prodenv, PLAT)[:2], prodenv, "production", rprod)
ok("production rejects PAYMENTS_LIVE_ENABLED=false (use staging for test money)",
   any("requires PAYMENTS_LIVE_ENABLED=true" in e for e in rprod.errors))

rtest = V.Result()
testlive = _base_platform_env(STRIPE_MODE="test", PAYMENTS_LIVE_ENABLED="true")
V.enforce_rules(*V.resolve(M, testlive, PLAT)[:2], testlive, "test", rtest)
ok("test env rejects PAYMENTS_LIVE_ENABLED=true",
   any("PAYMENTS_LIVE_ENABLED must be false" in e for e in rtest.errors))

# a fully-correct production+live config passes
rgood = V.Result()
good = _base_platform_env(
    ENVIRONMENT="production", APP_ENV="production", STRIPE_MODE="live",
    PAYMENTS_LIVE_ENABLED="true", STRIPE_ALLOW_LIVE="true", STRIPE_GATEWAY="real",
    STRIPE_SECRET_KEY="sk_live_x", STRIPE_PUBLISHABLE_KEY="pk_live_x",
    STRIPE_WEBHOOK_SECRET="whsec_x", GOOGLE_OAUTH_STUB="false", PAYOUT_STUB="false",
    NOTIFY_STUB="false", S3_STUB="false", PUBLIC_BASE_URL="https://petabyte.market",
    GOOGLE_REDIRECT_URI="https://petabyte.market/auth/google/callback")
gr, gs, rgood = V.resolve(M, good, PLAT)
V.enforce_rules(gr, gs, good, "production", rgood)
ok("a correct production+live config passes with no errors", rgood.ok)

# ---- unknown/undocumented var is reported ----
runk = V.Result()
V.find_unknown(M, _base_platform_env(TOTALLY_MADE_UP_VAR="x"), runk)
ok("an undocumented UPPER_CASE env var is reported as a warning",
   any("TOTALLY_MADE_UP_VAR" in w for w in runk.warnings))

# ---- GPU node env never receives platform secrets ----
leaky = {
    "PETABYTE_API_URL": "https://petabyte.market", "PETABYTE_SPEC_ID": "1",
    "PETABYTE_API_KEY": "node-token", "GPU_MODEL": "L4",
    # platform secrets that must NOT cross over:
    "STRIPE_SECRET_KEY": "sk_test_x", "DATABASE_URL": "postgresql://u:p@h/db",
    "SECRET_KEY": "s", "SERVER_PRIVATE_KEY": "f", "MAILGUN_API_KEY": "mg",
    "ADMIN_USERS": "info@petabyte.market",
}
gpu_pairs = G.collect(M, leaky, "gpu")
gpu_names = {n for n, _ in gpu_pairs}
forbidden = {"STRIPE_SECRET_KEY", "DATABASE_URL", "SECRET_KEY", "SERVER_PRIVATE_KEY",
             "MAILGUN_API_KEY", "ADMIN_USERS"}
ok("GPU env carries the node identity (PETABYTE_API_KEY/URL/SPEC_ID)",
   {"PETABYTE_API_KEY", "PETABYTE_API_URL", "PETABYTE_SPEC_ID"} <= gpu_names)
ok("GPU env contains NO platform secrets (Stripe/DB/keys/admin)",
   not (gpu_names & forbidden))
try:
    G.assert_gpu_safe([("PETABYTE_API_KEY", "ok"), ("STRIPE_SECRET_KEY", "leak")])
    ok("GPU deny-list refuses a platform-secret-shaped name", False)
except SystemExit as e:
    ok("GPU deny-list refuses a platform-secret-shaped name", e.code == 3)

# PETABYTE_AGENT_KEY (a local key PATH) is explicitly allowed on the GPU node
try:
    G.assert_gpu_safe([("PETABYTE_AGENT_KEY", "~/.petabyte/agent_ed25519.key")])
    ok("GPU allows the node's own local signing-key path (PETABYTE_AGENT_KEY)", True)
except SystemExit:
    ok("GPU allows the node's own local signing-key path (PETABYTE_AGENT_KEY)", False)

# NiceHash: the idle-mining CREDENTIALS (API key/secret, org id) must NEVER reach a GPU
# node, but the idle-mining RUNTIME config (payout address, miner image) is GPU-safe. The
# deny-list must distinguish them — a too-broad "NICEHASH" match would strip the runtime.
for _leak in ("NICEHASH_API_KEY", "NICEHASH_API_SECRET", "NICEHASH_ORG_ID"):
    try:
        G.assert_gpu_safe([("NICEHASH_ADDRESS", "addr"), (_leak, "secret")])
        ok(f"GPU deny-list refuses the NiceHash credential {_leak}", False)
    except SystemExit as e:
        ok(f"GPU deny-list refuses the NiceHash credential {_leak}", e.code == 3)
try:
    G.assert_gpu_safe([("NICEHASH_ADDRESS", "3F...addr"),
                       ("NICEHASH_IMAGE", "nicehash/nicehashminer:latest")])
    ok("GPU allows NiceHash idle-mining runtime config (ADDRESS + IMAGE, no credentials)", True)
except SystemExit:
    ok("GPU allows NiceHash idle-mining runtime config (ADDRESS + IMAGE, no credentials)", False)

# ---- secrets are never printed by the validator ----
SENTINEL = "SENTINEL_SECRET_VALUE_do_not_print_1234567890"
env = os.environ.copy()
env.update(_base_platform_env(SECRET_KEY=SENTINEL, STRIPE_MODE="test",
                              PAYMENTS_LIVE_ENABLED="false"))
proc = subprocess.run(
    [sys.executable, os.path.join(ROOT, "scripts", "validate_github_configuration.py"),
     "--env-name", "test"],
    capture_output=True, text=True, env=env)
out = proc.stdout + proc.stderr
ok("validator exits 0 on a valid test config", proc.returncode == 0)
ok("the secret VALUE is never printed", SENTINEL not in out)
ok("the secret is reported only as SET", "SECRET_KEY=SET" in out)

# ---- generated deploy env files are git-ignored ----
def _ignored(path):
    p = subprocess.run(["git", "check-ignore", path], cwd=ROOT, capture_output=True, text=True)
    return p.returncode == 0
ok(".env.platform.generated is git-ignored", _ignored(".env.platform.generated"))
ok(".env.gpu.generated is git-ignored", _ignored(".env.gpu.generated"))

# ---- the committed manifest is in sync (drift check passes) ----
drift = subprocess.run(
    [sys.executable, os.path.join(ROOT, "scripts", "check_configuration_drift.py")],
    capture_output=True, text=True)
ok("configuration drift check passes (manifest/code/workflows/template.env in sync)",
   drift.returncode == 0)

# ---- the deploy workflow cleans up EVERY generated env file it creates, unconditionally ----
# Not a loose ".generated"+"rm" substring check: we (1) discover the exact --out targets the
# workflow generates, (2) require each to be explicitly `rm`'d on the same command line, and
# (3) require that cleanup step to run `if: always()` so a mid-deploy failure can't leave a
# generated secret file behind on the runner.
import re as _re  # noqa: E402
_wf_path = os.path.join(ROOT, ".github", "workflows", "deploy-server.yml")
_wf_text = open(_wf_path).read()
_gen_outs = set(_re.findall(r'--out\s+(\S+\.generated)', _wf_text))
ok("deploy workflow generates at least one scoped env file (--out *.generated)",
   bool(_gen_outs))

_wf = yaml.safe_load(_wf_text)
_steps = _wf.get("jobs", {}).get("deploy", {}).get("steps", []) or []


def _cleanup_guard(fname):
    """Return the `if:` guard of the step that removes fname on the runner, else None.
    Matches only an `rm ... <fname>` on the SAME line (so the unrelated `rm` of the remote
    /tmp incoming file in the generate step is not mistaken for the runner cleanup)."""
    for s in _steps:
        for line in (s.get("run", "") or "").splitlines():
            if _re.search(r'\brm\b', line) and fname in line:
                return str(s.get("if", "")).strip()
    return None


_guards = {f: _cleanup_guard(f) for f in _gen_outs}
ok("deploy workflow explicitly deletes every generated env file it creates (after use)",
   bool(_gen_outs) and all(v is not None for v in _guards.values()))
ok("the generated-secret cleanup runs unconditionally (if: always()) — a failed deploy "
   "never leaves the env file on the runner",
   bool(_gen_outs) and all((v or "").replace(" ", "") == "always()" for v in _guards.values()))
ok("deploy workflow runs the configuration validator before generating env",
   "validate_github_configuration.py" in _wf_text)

print(f"\n=== config: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
