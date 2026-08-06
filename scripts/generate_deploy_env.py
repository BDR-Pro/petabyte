#!/usr/bin/env python3
"""Generate the deployment env file(s) from the resolved GitHub Variables + Secrets.

This runs INSIDE the deploy workflow, AFTER validate_github_configuration.py has passed.
It never invents values: non-sensitive Variables get their documented defaults when unset;
Secrets are taken from the environment and included only when actually present. The output
is written with 0600 permissions, is git-ignored, is never printed, and must be deleted
from the runner after it is uploaded.

Two scopes, two files:
  --target platform  -> .env.platform.generated   (the API server's /etc/lumaris/lumaris.env)
  --target gpu       -> .env.gpu.generated         (a seller GPU node's agent env)

SECURITY — the GPU node file is scope-filtered to `gpu` config ONLY and, as defence in
depth, a hard deny-list refuses to emit any platform-secret-shaped name into it. A GPU
node must NEVER receive: Stripe secrets, database/Redis credentials, admin credentials,
the platform private signing key (SERVER_PRIVATE_KEY), or any buyer financial data.

Usage:
    python scripts/generate_deploy_env.py --target platform --out .env.platform.generated
    python scripts/generate_deploy_env.py --target gpu      --out .env.gpu.generated
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    print("::error::PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST = os.path.join(ROOT, "config", "github_configuration_manifest.yaml")

# Defence-in-depth deny-list: names that must NEVER appear in a GPU node's env file, even
# if a scoping mistake were ever made. Matched case-insensitively as a whole-name regex.
GPU_FORBIDDEN = re.compile(
    r"(SECRET_KEY|SERVER_PRIVATE_KEY|PRIVATE_KEY|DATABASE_URL|POSTGRES|REDIS|"
    r"STRIPE|PAYMENT|PAYOUT|ADMIN|MAILGUN_API_KEY|MAILCHIMP|SENDGRID|POSTMARK|"
    r"AWS_SECRET|AWS_ACCESS|CIRCLE|TREMENDOUS|NICEHASH|GOOGLE_CLIENT|GATEWAY_TOKEN|"
    r"SANCTIONS|SESSION|ENCRYPTION|WEBHOOK|DEPLOY_SSH|DROPLET|SENTRY_DSN|TEE_TRUSTED)",
    re.IGNORECASE,
)
# PETABYTE_AGENT_KEY is a PATH to the node's OWN local signing key, not a platform secret —
# allow it explicitly so the broad PRIVATE_KEY pattern above doesn't catch a false positive.
GPU_ALLOW_EXACT = {"PETABYTE_AGENT_KEY"}


def _get_env(env: dict, name: str, aka: str | None) -> str | None:
    for key in (name, aka):
        if key and env.get(key, "") != "":
            return env[key]
    return None


def collect(manifest: dict, env: dict, scope: str):
    """Return an ordered list of (name, value) for one scope, defaults applied for missing
    non-sensitive Variables; Secrets included only when present in the environment."""
    out: list[tuple[str, str]] = []
    for section, is_secret in (("variables", False), ("secrets", True)):
        for name, meta in manifest.get(section, {}).items():
            if scope not in meta.get("scope", []):
                continue
            aka = meta.get("aka")
            val = _get_env(env, name, aka)
            if val is None:
                if is_secret:
                    continue  # never fabricate a secret; absent -> omitted
                default = meta.get("default")
                if default is None:
                    continue  # optional variable with no default -> omit rather than blank
                val = str(default)
            out.append((name, val))
    out.sort(key=lambda kv: kv[0])
    return out


def assert_gpu_safe(pairs: list[tuple[str, str]]) -> None:
    leaked = [n for n, _ in pairs
              if n not in GPU_ALLOW_EXACT and GPU_FORBIDDEN.search(n)]
    if leaked:
        print("::error::REFUSING to write GPU env — platform-secret-shaped names present: "
              + ", ".join(sorted(leaked)), file=sys.stderr)
        raise SystemExit(3)


def write_env_file(path: str, pairs: list[tuple[str, str]], header: str) -> None:
    # Create with 0600 from the start (never a window where it is world-readable).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(header)
        for name, val in pairs:
            f.write(f"{name}={val}\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600, belt and suspenders


_PLATFORM_HEADER = (
    "# ================= Petabyte API server env — GENERATED, DO NOT COMMIT =================\n"
    "# Generated at deploy time from GitHub Variables + Secrets by\n"
    "# scripts/generate_deploy_env.py. Do not hand-edit on the server: the next deploy\n"
    "# overwrites it. Change values in GitHub → Settings → Secrets and variables → Actions.\n"
    "# This file contains credentials. It is 0600, git-ignored, never uploaded as an\n"
    "# artifact, and deleted from the runner after upload.\n\n"
)
_GPU_HEADER = (
    "# ================= Petabyte GPU node env — GENERATED, DO NOT COMMIT =================\n"
    "# Generated at deploy time from GitHub Variables + Secrets by\n"
    "# scripts/generate_deploy_env.py (scope=gpu ONLY). It carries the node's identity,\n"
    "# enrollment token, heartbeat + GPU runtime config, and the public API/telemetry URL.\n"
    "# It NEVER contains platform secrets (Stripe, DB/Redis, admin, platform signing key,\n"
    "# buyer financial data). 0600, git-ignored, deleted from the runner after upload.\n\n"
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--target", choices=["platform", "gpu"], required=True)
    ap.add_argument("--out", required=True, help="Output path for the generated env file.")
    args = ap.parse_args(argv)

    from config_context import hydrate_env
    hydrate_env()  # merge GitHub vars/secrets JSON into the env, if the workflow passed them

    with open(args.manifest) as f:
        manifest = yaml.safe_load(f)

    env = dict(os.environ)
    pairs = collect(manifest, env, args.target)

    if args.target == "gpu":
        assert_gpu_safe(pairs)
        header = _GPU_HEADER
    else:
        header = _PLATFORM_HEADER

    write_env_file(args.out, pairs, header)
    # Print ONLY names + count, never values.
    names = ", ".join(n for n, _ in pairs)
    print(f"wrote {args.out} ({args.target}, 0600): {len(pairs)} keys")
    print(f"keys: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
