#!/usr/bin/env python3
"""Developer helper for the single ENV_VARS GitHub Variable.

    python scripts/env_bundle.py generate   # print a ready-to-paste ENV_VARS bundle
    python scripts/env_bundle.py validate    # validate a bundle (file / stdin / $ENV_VARS)
    python scripts/env_bundle.py list        # list documented Variables + Secret NAMES

`generate` emits every NON-SECRET Variable from the manifest as `KEY=default;` lines — it
NEVER includes a secret value (secrets are excluded entirely) and never emits the bootstrap
Variables (ENV_VARS / DEPLOY_CONFIG_FROM_GITHUB stay standalone). Paste the output into the
GitHub Repository Variable named ENV_VARS.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import env_vars as ev  # noqa: E402

DEFAULT_SCOPES = {"platform", "observability"}


def _vars(manifest):
    return manifest.get("variables", {})


def _in_scope(meta, scopes):
    return scopes is None or bool(set(meta.get("scope", [])) & scopes)


def cmd_generate(args) -> int:
    manifest = ev._load_manifest()
    scopes = None if args.scope == "all" else set(args.scope.split(","))
    lines = []
    for name in sorted(_vars(manifest)):
        meta = _vars(manifest)[name]
        if name in ev.BOOTSTRAP_VARS:
            continue                       # bootstrap Variables stay standalone
        if ev.is_secret_name(name, manifest):
            continue                       # never emit a secret (defence in depth)
        if not _in_scope(meta, scopes):
            continue
        d = meta.get("default")
        d = "" if d in (None,) else str(d)
        lines.append(f"{name}={d};")
    print("\n".join(lines))
    print(f"\n# {len(lines)} non-secret variables (scope: {args.scope}). "
          "Paste the lines above into the ENV_VARS GitHub Variable.", file=sys.stderr)
    return 0


def _read_bundle(args) -> str:
    if args.file:
        with open(args.file) as f:
            return f.read()
    if os.environ.get("ENV_VARS"):
        return os.environ["ENV_VARS"]
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def cmd_validate(args) -> int:
    manifest = ev._load_manifest()
    text = _read_bundle(args)
    if not text.strip():
        print("::error::no bundle provided (use --file, pipe stdin, or set $ENV_VARS)")
        return 2
    values, perrors = ev.parse_bundle(text)
    errors = [f"parse: {e}" for e in perrors]
    errors += ev.check_no_secrets(values, manifest)
    errors += [f"{e}" for e in ev.check_known(values, manifest)]
    print(f"parsed {len(values)} variable(s).")
    if errors:
        for e in errors:
            print(f"  ::error::{e}")
        print(f"\nFAILED: {len(errors)} problem(s). (values are never printed)")
        return 1
    print("OK: ENV_VARS bundle is valid (syntax, no secrets, all keys known).")
    return 0


def cmd_list(args) -> int:
    manifest = ev._load_manifest()
    print("== Variables (non-secret — belong in ENV_VARS) ==")
    for name in sorted(_vars(manifest)):
        meta = _vars(manifest)[name]
        if ev.is_secret_name(name, manifest) or name in ev.BOOTSTRAP_VARS:
            continue
        d = meta.get("default")
        d = "(empty)" if d in (None, "") else d
        print(f"  {name:32} scope={'/'.join(meta.get('scope', []))!s:22} default={d}")
    print("\n== Bootstrap Variables (stay standalone, NOT in ENV_VARS) ==")
    for name in sorted(ev.BOOTSTRAP_VARS):
        print(f"  {name}")
    print("\n== Secrets (individually managed GitHub Secrets — values never shown) ==")
    for name in sorted(manifest.get("secrets", {})):
        req = "required" if manifest["secrets"][name].get("required") else "optional"
        print(f"  {name:32} [{req}]")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="print a ready-to-paste ENV_VARS bundle")
    g.add_argument("--scope", default="platform,observability",
                   help="comma scopes or 'all' (default platform,observability)")
    g.set_defaults(func=cmd_generate)
    v = sub.add_parser("validate", help="validate a bundle (file/stdin/$ENV_VARS)")
    v.add_argument("--file", default="")
    v.set_defaults(func=cmd_validate)
    ls = sub.add_parser("list", help="list documented Variables + Secret names")
    ls.set_defaults(func=cmd_list)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
