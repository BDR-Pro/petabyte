"""Hydrate os.environ from GitHub configuration for the validator + env generator.

New (bundled) model — the source of truth for NON-SECRET config is ONE GitHub Variable:

    env:
      ENV_VARS:                 ${{ vars.ENV_VARS }}
      DEPLOY_CONFIG_FROM_GITHUB: ${{ vars.DEPLOY_CONFIG_FROM_GITHUB }}
      SECRETS_JSON:             ${{ toJSON(secrets) }}
      VARS_JSON:                ${{ toJSON(vars) }}   # only to DETECT legacy individual vars

Precedence (highest first): GitHub Secrets > ENV_VARS > manifest defaults. Secrets and
ENV_VARS keys are DISJOINT by construction (a secret-classified key is refused inside
ENV_VARS), so there is never an ambiguous same-key conflict. Manifest defaults are applied
later by the validator/generator when a key is unset.

When ENV_VARS is present the legacy per-variable JSON (VARS_JSON) is NOT used as config —
only to report conflicting legacy individual Variables — so the two sources are never
silently mixed. When ENV_VARS is absent we fall back to the legacy VARS_JSON path for
backward compatibility during migration. Nothing here is printed.
"""
from __future__ import annotations

import json
import os

import env_vars as _ev

# Keys that appear in the GitHub `secrets` context but are not deployment config.
_SKIP = {"GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"}


def _merge(blob: str) -> int:
    if not blob:
        return 0
    try:
        data = json.loads(blob)
    except (ValueError, TypeError):
        return 0
    n = 0
    for k, v in (data or {}).items():
        if k in _SKIP or v is None:
            continue
        if os.environ.get(k):  # do not clobber an explicitly-set value
            continue
        os.environ[k] = str(v)
        n += 1
    return n


def using_bundle() -> bool:
    """True when the new single-variable ENV_VARS bundle is present."""
    return bool((os.environ.get("ENV_VARS") or "").strip())


def hydrate_env() -> None:
    """Apply GitHub config to os.environ. ENV_VARS bundle first (non-secret), then Secrets.

    Precedence is preserved because secret keys can only come from SECRETS_JSON and
    non-secret keys only from ENV_VARS (they are disjoint). `_merge` never clobbers an
    already-set value, so an explicit test/CLI override still wins.
    """
    if using_bundle():
        values, _errors = _ev.parse_bundle(os.environ["ENV_VARS"])
        # parse/validation errors are surfaced by validate_github_configuration.py; here we
        # only apply the well-formed, non-secret values so downstream tools can resolve.
        _ev.apply_to_environ(values)
    else:
        _merge(os.environ.get("VARS_JSON", ""))   # legacy migration fallback
    _merge(os.environ.get("SECRETS_JSON", ""))    # secrets always available (win by disjointness)
