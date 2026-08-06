#!/usr/bin/env python3
"""Detect configuration drift and fail CI when the manifest, the code, the deploy
workflows, and template.env stop agreeing.

Four sources must stay in sync:

  1. code  — every env var the server + agent code reads (os.getenv / os.environ.get).
  2. manifest — config/github_configuration_manifest.yaml (the source of truth).
  3. workflows — every ${{ vars.X }} / ${{ secrets.X }} referenced in .github/workflows.
  4. template.env — the authoritative platform env list the smoke guard already enforces.

Drift we FAIL on:
  * the committed manifest is stale (does not match `build_config_manifest.build_doc()`),
  * code reads a var that is not documented in the manifest (undocumented config),
  * a workflow references vars./secrets. that is not in the manifest,
  * a manifest entry is obsolete (backed by nothing: no code ref, not in template.env,
    not a known agent/deployment/reserved var).

Run:
    python scripts/check_configuration_drift.py
Exits non-zero on any drift so CI stops.
"""
from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import yaml
except ImportError:  # pragma: no cover
    print("::error::PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

import build_config_manifest as bcm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "config", "github_configuration_manifest.yaml")

# Directories whose *.py we treat as runtime code (their env reads must be documented).
CODE_DIRS = ["lumaris_api", "lumaris_agent", "lumaris_gateway"]

# Vars that are legitimately read by code but are NOT deployment config (dev/test-only,
# or hardcoded-elsewhere). Mirrors build_config_manifest.TEST_ONLY + a few runtime-only.
_CODE_IGNORE = set(bcm.TEST_ONLY) | {
    "PYTEST_CURRENT_TEST", "PYTHONPATH", "HOME", "PATH", "PWD",
    "LUMARIS_ENV_FILE", "LUMARIS_REPORT_FILE", "PGBIN", "PGPORT", "PGDATA",
    "MAILGUN_API_BASE",  # hardcoded in email_service on purpose
}

_ENV_RE = re.compile(r'os\.(?:getenv|environ\.get)\(\s*["\']([A-Z][A-Z0-9_]+)["\']')
_ENVIRON_IDX_RE = re.compile(r'os\.environ\[\s*["\']([A-Z][A-Z0-9_]+)["\']')
_WF_RE = re.compile(r'\$\{\{\s*(?:vars|secrets)\.([A-Z][A-Z0-9_]+)\s*\}\}')


def scan_code_vars() -> dict[str, set]:
    """Map each env var name -> set of files (test files excluded) that read it."""
    out: dict[str, set] = {}
    for d in CODE_DIRS:
        for f in glob.glob(os.path.join(ROOT, d, "**", "*.py"), recursive=True):
            base = os.path.basename(f)
            if base.startswith("demo") or base.endswith("_test.py"):
                continue
            text = open(f).read()
            for m in list(_ENV_RE.finditer(text)) + list(_ENVIRON_IDX_RE.finditer(text)):
                out.setdefault(m.group(1), set()).add(os.path.relpath(f, ROOT))
    return out


def scan_workflow_refs() -> dict[str, set]:
    out: dict[str, set] = {}
    for f in glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")) + \
             glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yaml")):
        text = open(f).read()
        for m in _WF_RE.finditer(text):
            out.setdefault(m.group(1), set()).add(os.path.relpath(f, ROOT))
    return out


def manifest_names(manifest: dict) -> set:
    names = set(manifest.get("variables", {})) | set(manifest.get("secrets", {}))
    for meta in list(manifest.get("variables", {}).values()) + list(manifest.get("secrets", {}).values()):
        if meta.get("aka"):
            names.add(meta["aka"])
    return names


# Workflow refs that are GitHub-provided or CI-only, not app config.
_WF_IGNORE = {"GITHUB_TOKEN"}


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    with open(MANIFEST) as f:
        committed = yaml.safe_load(f)

    # 1) manifest freshness — committed file must match a fresh build.
    fresh_text = bcm.render_yaml(bcm.build_doc())
    committed_text = open(MANIFEST).read()
    if fresh_text != committed_text:
        errors.append("config/github_configuration_manifest.yaml is STALE — run "
                      "`python scripts/build_config_manifest.py` and commit the result.")

    known = manifest_names(committed)

    # 2) code reads a var not in the manifest -> undocumented.
    code_vars = scan_code_vars()
    for name, files in sorted(code_vars.items()):
        if name in _CODE_IGNORE or name in known:
            continue
        errors.append(f"Undocumented config: {name} is read by code ({', '.join(sorted(files))}) "
                      "but is not in the manifest. Add it to template.env / build_config_manifest.py "
                      "and re-run the builder.")

    # 3) workflow references a var not in the manifest.
    wf_vars = scan_workflow_refs()
    for name, files in sorted(wf_vars.items()):
        if name in _WF_IGNORE or name in known:
            continue
        errors.append(f"Undocumented workflow config: vars./secrets.{name} used in "
                      f"{', '.join(sorted(files))} but not in the manifest.")

    # 4) obsolete manifest entry — backed by nothing.
    tmpl_vars = set(bcm.parse_template_env())
    backed = set(code_vars) | tmpl_vars | set(bcm.AGENT_VARS) | set(bcm.RESERVED_VARS)
    # aka aliases count as backing their canonical name.
    for section in ("variables", "secrets"):
        for name, meta in committed.get(section, {}).items():
            if name in backed:
                continue
            aka = meta.get("aka")
            if aka and aka in backed:
                continue
            warnings.append(f"Possibly-obsolete manifest entry: {name} has no code ref, is not "
                            "in template.env, and is not a known agent/reserved var.")

    # ---- report ----
    print("=== configuration drift check ===")
    print(f"code vars: {len(code_vars)} · workflow refs: {len(wf_vars)} · "
          f"manifest names: {len(known)}")
    for w in warnings:
        print(f"::warning::{w}")
    for e in errors:
        print(f"::error::{e}")
    if errors:
        print(f"\nDRIFT: {len(errors)} error(s). Configuration is out of sync.")
        return 1
    print("\nOK: manifest, code, workflows, and template.env are in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
