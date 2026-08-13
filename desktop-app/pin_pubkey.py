"""pin_pubkey.py — bake the release PUBLIC key into the exe at build time.

The auto-updater (updater.py) applies an update only if it is signed by the PINNED release key.
That key must be compiled into the binary (the seller's machine has no PETABYTE_RELEASE_PUBKEY
env), so the release workflow runs this BEFORE build_exe.py to rewrite `_PINNED_RELEASE_PUBKEY`
from the PETABYTE_RELEASE_PUBKEY value (a GitHub Actions *variable* — a public key, not a secret).

Behaviour:
  * env set + valid  -> rewrite updater.py, exit 0.
  * env unset/blank  -> emit a GitHub warning and exit 0 (non-breaking: the exe still builds but
                        will REFUSE auto-updates, fail-closed, until the key is configured).
  * env set + invalid-> exit 1 (a bad pin is worse than no pin — fail the build loudly).
"""
from __future__ import annotations

import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATER = os.path.join(HERE, "updater.py")


def main() -> int:
    pub = (os.getenv("PETABYTE_RELEASE_PUBKEY") or "").strip()
    if not pub:
        print("::warning::PETABYTE_RELEASE_PUBKEY is not set — the built exe will REFUSE "
              "auto-updates (fail-closed). Set the repo variable to enable signed auto-update.")
        return 0
    try:
        if len(base64.b64decode(pub, validate=True)) != 32:
            raise ValueError("not a 32-byte Ed25519 public key")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"PETABYTE_RELEASE_PUBKEY is invalid: {e}\n")
        return 1

    src = open(UPDATER, encoding="utf-8").read()
    new, n = re.subn(r'_PINNED_RELEASE_PUBKEY = "[^"]*"',
                     f'_PINNED_RELEASE_PUBKEY = "{pub}"', src, count=1)
    if n != 1:
        sys.stderr.write("could not find _PINNED_RELEASE_PUBKEY assignment in updater.py\n")
        return 1
    open(UPDATER, "w", encoding="utf-8").write(new)
    print(f"pinned release public key into updater.py ({pub[:12]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
