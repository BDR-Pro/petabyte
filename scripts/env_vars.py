"""Parser + secret-guard for the single `ENV_VARS` GitHub Variable.

Instead of 100+ individual GitHub Variables, ALL non-sensitive configuration is bundled in
one Repository Variable named ENV_VARS, as `KEY=value;` pairs separated by semicolons
(newlines are just formatting). Secrets stay as individual GitHub Secrets and NEVER appear
in ENV_VARS.

ENV_VARS is treated strictly as DATA — never eval'd, never sourced as shell. This module:
  * parses the bundle (semicolon split, trims, ignores blanks, preserves '=' in values,
    validates names, rejects duplicates / null bytes / newline-injected values / entries
    without '='),
  * classifies keys against config/github_configuration_manifest.yaml + a denylist so a
    secret can never be smuggled in through ENV_VARS,
  * detects legacy individual GitHub Variables so the two sources are never silently mixed.

No value is ever included in an error message (only key names / sanitized snippets).
"""
from __future__ import annotations

import os
import re

import build_config_manifest as _bcm  # is_secret() heuristic reused for the denylist

NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

# Bootstrap/deployment controls that legitimately remain standalone GitHub Variables
# (they must exist BEFORE ENV_VARS is parsed), so they are not treated as "legacy".
BOOTSTRAP_VARS = {"ENV_VARS", "DEPLOY_CONFIG_FROM_GITHUB"}

# Defence-in-depth denylist (independent of the manifest): any key matching these is
# refused inside ENV_VARS even if the manifest somehow missed it.
_DENY_SUBSTR = ("SECRET", "PASSWORD", "PASSWD", "TOKEN", "PRIVATE_KEY", "API_KEY", "APIKEY",
                "CREDENTIAL", "_DSN", "SSH_KEY", "WEBHOOK_SECRET", "CLIENT_SECRET",
                "ACCESS_KEY", "SECRET_KEY")


def _snippet(s: str, n: int = 32) -> str:
    """A short, safe snippet of a NAME/entry for an error (never a value)."""
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "\\0")
    return s if len(s) <= n else s[:n] + "…"


def parse_bundle(text: str):
    """Parse an ENV_VARS bundle. Returns (values: dict[str,str], errors: list[str]).

    Rules: split on ';'; trim each entry; ignore blank entries; an entry must contain '='
    (split on the FIRST '=' only, so values may contain '='); the key must match
    ^[A-Z_][A-Z0-9_]*$; duplicate keys, null bytes, and newline-injected values are
    rejected. Never raises.
    """
    values: dict[str, str] = {}
    errors: list[str] = []
    if text is None:
        return values, errors
    if "\x00" in text:
        errors.append("ENV_VARS contains a null byte (0x00) — rejected.")
        return values, errors

    seen: set[str] = set()
    for raw in text.split(";"):
        entry = raw.strip()
        if not entry:
            continue  # blank entry (trailing ';', blank line) — ignore
        # A newline that survives .strip() is INSIDE the entry -> newline injection.
        if "\n" in entry or "\r" in entry:
            errors.append(f"malformed entry (embedded newline) near '{_snippet(entry)}'")
            continue
        if "=" not in entry:
            errors.append(f"entry without '=': '{_snippet(entry)}'")
            continue
        key, value = entry.split("=", 1)     # FIRST '=' only -> preserves '=' in value
        key = key.strip()
        value = value.strip()
        if not NAME_RE.match(key):
            errors.append(f"invalid variable name: '{_snippet(key)}' "
                          "(must match ^[A-Z_][A-Z0-9_]*$)")
            continue
        if "\x00" in value or "\n" in value or "\r" in value:
            errors.append(f"{key}: value contains a forbidden control character")
            continue
        if key in seen:
            errors.append(f"duplicate key: {key}")
            continue
        seen.add(key)
        values[key] = value
    return values, errors


# ------------------------------------------------------------------ classification ----
_manifest_cache = None


def _load_manifest(path: str | None = None) -> dict:
    global _manifest_cache
    if _manifest_cache is not None and path is None:
        return _manifest_cache
    import yaml
    p = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "config", "github_configuration_manifest.yaml")
    with open(p) as f:
        m = yaml.safe_load(f) or {}
    if path is None:
        _manifest_cache = m
    return m


def secret_names(manifest: dict) -> set:
    names = set(manifest.get("secrets", {}))
    for meta in manifest.get("secrets", {}).values():
        if meta.get("aka"):
            names.add(meta["aka"])
    return names


def variable_names(manifest: dict) -> set:
    names = set(manifest.get("variables", {}))
    for meta in manifest.get("variables", {}).values():
        if meta.get("aka"):
            names.add(meta["aka"])
    return names


def is_secret_name(name: str, manifest: dict | None = None) -> bool:
    """True if `name` is a secret per the manifest OR the defense-in-depth denylist."""
    manifest = manifest or _load_manifest()
    if name in secret_names(manifest):
        return True
    if any(s in name for s in _DENY_SUBSTR):
        return True
    return _bcm.is_secret(name)


def check_no_secrets(values: dict, manifest: dict | None = None) -> list[str]:
    """Reject any secret-classified key found inside ENV_VARS (value NEVER printed)."""
    manifest = manifest or _load_manifest()
    errs = []
    for key in values:
        if is_secret_name(key, manifest):
            errs.append(f"{key} is classified as a GitHub Secret and cannot be supplied "
                        "through ENV_VARS.")
    return errs


def check_known(values: dict, manifest: dict | None = None) -> list[str]:
    """Report keys not documented as a Variable in the manifest."""
    manifest = manifest or _load_manifest()
    known = variable_names(manifest)
    return [f"unknown variable (not in the manifest): {k}"
            for k in values if k not in known and k not in BOOTSTRAP_VARS]


def detect_legacy_individual_vars(vars_context: dict, manifest: dict | None = None) -> list[str]:
    """Given the GitHub `vars` context (individual Variables), report any non-bootstrap
    manifest Variable still configured individually — these must move into ENV_VARS so the
    two sources are never silently mixed."""
    manifest = manifest or _load_manifest()
    known = variable_names(manifest)
    legacy = []
    for name in vars_context or {}:
        if name in BOOTSTRAP_VARS:
            continue
        if name in known:
            legacy.append(name)
    return sorted(legacy)


def apply_to_environ(values: dict, manifest: dict | None = None) -> int:
    """Apply parsed NON-SECRET values to os.environ without clobbering an explicit value.
    A secret-classified key is skipped defensively (validation fails on it separately)."""
    manifest = manifest or _load_manifest()
    n = 0
    for k, v in values.items():
        if is_secret_name(k, manifest):
            continue
        if os.environ.get(k):
            continue
        os.environ[k] = v
        n += 1
    return n
