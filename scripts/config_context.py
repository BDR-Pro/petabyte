"""Hydrate os.environ from the GitHub Actions `vars` and `secrets` contexts.

The deploy workflow passes the entire configuration as two JSON blobs so the YAML stays
small and can never fall out of sync with the manifest:

    env:
      VARS_JSON:    ${{ toJSON(vars) }}
      SECRETS_JSON: ${{ toJSON(secrets) }}

Both validate_github_configuration.py and generate_deploy_env.py call hydrate_env() first,
so they see the real GitHub Variables + Secrets as ordinary environment variables. Values
are merged in WITHOUT overwriting anything already explicitly set in the process env (so a
test or a manual `--` override still wins). Nothing here is printed.
"""
from __future__ import annotations

import json
import os

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
        # do not clobber an explicitly-set value already in the environment
        if os.environ.get(k):
            continue
        os.environ[k] = str(v)
        n += 1
    return n


def hydrate_env() -> None:
    """Merge $VARS_JSON and $SECRETS_JSON (if present) into os.environ."""
    _merge(os.environ.get("VARS_JSON", ""))
    _merge(os.environ.get("SECRETS_JSON", ""))
