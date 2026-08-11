"""Self-update the Petabyte Desktop Agent from GitHub Releases — SIGNED updates only.

On startup (and every few hours) the running .exe asks GitHub for the latest release. If the
tag is newer than the bundled VERSION it downloads the attached PetabyteAgent.exe AND a signed
manifest, and swaps itself in ONLY after verifying the download against that manifest. Windows
can't overwrite a running exe, so a tiny detached .bat waits for exit, replaces the file, and
relaunches.

SECURITY (why the manifest exists): an auto-updater that applies whatever is attached to a
GitHub release is fleet-wide remote code execution for anyone who can publish a release (repo
write, a leaked CI/PAT token, a rogue maintainer). So an update is applied ONLY when:
  * a release public key is PINNED into this build (_PINNED_RELEASE_PUBKEY / env override), and
  * the downloaded exe's SHA-256 matches the manifest's, and
  * the manifest is Ed25519-signed by that pinned key.
Any missing/invalid piece -> the update is REFUSED (fail closed). No pin -> no auto-update.

No-ops unless running as a frozen Windows exe. Configure the source repo with
PETABYTE_UPDATE_REPO (default: BDR-Pro/petabyte).
"""
import base64
import hashlib
import json
import logging
import os
import sys
import tempfile
import threading
import time
import urllib.request

try:
    from version import VERSION
except Exception:
    VERSION = "0.0.0"

REPO = os.getenv("PETABYTE_UPDATE_REPO", "BDR-Pro/petabyte")
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY_S = int(os.getenv("PETABYTE_UPDATE_INTERVAL_S", str(6 * 3600)))
ASSET_NAME = "PetabyteAgent.exe"
MANIFEST_ASSET_NAME = "PetabyteAgent.exe.manifest.json"

# The release signing PUBLIC key (base64 raw Ed25519), PINNED at build time. The private key
# lives only in the release signer (offline / CI secret). Empty here on purpose: a build that
# ships without a pinned key refuses to auto-update rather than trusting an unsigned binary.
# Override for staging/tests with PETABYTE_RELEASE_PUBKEY.
_PINNED_RELEASE_PUBKEY = ""

# Fields covered by the manifest signature (the exe digest is the security-critical one).
_MANIFEST_CORE = ("asset", "version", "sha256")


def _pinned_pubkey() -> str:
    return (os.getenv("PETABYTE_RELEASE_PUBKEY") or _PINNED_RELEASE_PUBKEY or "").strip()


def _canonical(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_update(exe_path: str, manifest: dict, pubkey_b64: str,
                  expected_asset: str = None, expected_version: str = None):
    """Return (ok: bool, reason: str). FAIL CLOSED — any missing/invalid piece is a refusal.

    Checks: a pinned key is configured; the manifest carries asset/version/sha256 + a signature;
    the downloaded file's SHA-256 equals the manifest's; the manifest is Ed25519-signed by the
    pinned key over the canonical core fields; and (when expected_asset/expected_version are
    given) the SIGNED manifest actually targets THIS release — so a signer-less publisher cannot
    replay an older valid exe+manifest under a newer GitHub tag."""
    if not pubkey_b64:
        return False, "no pinned release public key (refusing to apply an unsigned update)"
    try:
        core = {k: manifest.get(k) for k in _MANIFEST_CORE}
        if any(core[k] in (None, "") for k in _MANIFEST_CORE):
            return False, "manifest missing required fields (asset/version/sha256)"
        sig = manifest.get("sig")
        if not sig:
            return False, "manifest has no signature"
        actual = _sha256_file(exe_path)
        if actual.lower() != str(core["sha256"]).lower():
            return False, "sha256 mismatch — downloaded file is not the signed release"
        # Bind the signed manifest to the selected release (anti-replay). Checked BEFORE the
        # signature so a mismatch is reported clearly, but note the signature covers these same
        # fields, so an attacker cannot forge asset/version to match either.
        if expected_asset is not None and str(core["asset"]) != str(expected_asset):
            return False, (f"manifest asset '{core['asset']}' != expected '{expected_asset}' "
                           "(replayed manifest for a different asset)")
        if expected_version is not None and _ver(str(core["version"])) != _ver(str(expected_version)):
            return False, (f"manifest version '{core['version']}' != release '{expected_version}' "
                           "(replayed older signed release under a newer tag)")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
        try:
            pub.verify(base64.b64decode(sig), _canonical(core))
        except InvalidSignature:
            return False, "signature does not verify against the pinned release key"
        return True, "verified"
    except Exception as e:  # noqa: BLE001 — any parsing/crypto error is a refusal, never a pass
        return False, f"verification error: {e}"


def _ver(s: str):
    """Parse 'v1.2.3' -> (1,2,3); tolerant of junk."""
    out = []
    for part in s.lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def _latest():
    """Return (tag, exe_url, manifest_url) for the latest release."""
    req = urllib.request.Request(
        LATEST_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "petabyte-agent"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    tag = data.get("tag_name", "")
    exe_url = manifest_url = None
    for a in data.get("assets", []):
        name = a.get("name", "").lower()
        if name == ASSET_NAME.lower():
            exe_url = a.get("browser_download_url")
        elif name == MANIFEST_ASSET_NAME.lower():
            manifest_url = a.get("browser_download_url")
    return tag, exe_url, manifest_url


def _fetch_bytes(url: str, timeout: int = 60, max_bytes: int = 64 * 1024) -> bytes:
    # Bound the read: a signed manifest is a few hundred bytes. Reading an attacker-published
    # oversized "manifest" fully would cause memory pressure BEFORE signature verification can
    # reject it. Read at most max_bytes+1 and refuse anything larger.
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"manifest exceeds {max_bytes} bytes — refusing")
    return data


def _swap_and_restart(current: str, newfile: str):
    """Windows-safe self-replace: detached .bat waits, moves, relaunches."""
    bat = os.path.join(tempfile.gettempdir(), "petabyte_update.bat")
    with open(bat, "w", encoding="ascii") as f:
        f.write("@echo off\r\n")
        f.write("timeout /t 2 /nobreak >nul\r\n")
        f.write(f'move /y "{newfile}" "{current}" >nul\r\n')
        f.write(f'start "" "{current}"\r\n')
        f.write('del "%~f0"\r\n')
    DETACHED = 0x00000008
    import subprocess
    subprocess.Popen(["cmd", "/c", bat], creationflags=DETACHED, close_fds=True)
    logging.info("update verified — restarting to apply…")
    os._exit(0)


def _check_once():
    if not getattr(sys, "frozen", False) or os.name != "nt":
        return  # only the packaged Windows exe self-updates
    try:
        tag, url, manifest_url = _latest()
        if not tag or not url:
            return
        if _ver(tag) <= _ver(VERSION):
            logging.info(f"agent up to date (v{VERSION})")
            return
        # Refuse BEFORE downloading if this build cannot verify signatures — never trust an
        # unsigned/unverifiable binary.
        if not _pinned_pubkey():
            logging.error("update %s available but no pinned release key is configured — "
                          "refusing to apply an unsigned update", tag)
            return
        if not manifest_url:
            logging.error("update %s has no signed manifest asset (%s) — refusing",
                          tag, MANIFEST_ASSET_NAME)
            return
        logging.info(f"update {tag} available (current v{VERSION}) — downloading + verifying")
        current = sys.executable
        newfile = current + ".new"
        with urllib.request.urlopen(url, timeout=180) as r, open(newfile, "wb") as f:
            f.write(r.read())
        if os.path.getsize(newfile) < 1_000_000:      # sanity: real exe is tens of MB
            os.remove(newfile)
            logging.warning("downloaded update looked too small — skipped")
            return
        try:
            manifest = json.loads(_fetch_bytes(manifest_url, timeout=30).decode())
        except Exception as e:  # noqa: BLE001
            os.remove(newfile)
            logging.error("could not fetch/parse the signed manifest — refusing update: %s", e)
            return
        ok, reason = verify_update(newfile, manifest, _pinned_pubkey(),
                                   expected_asset=ASSET_NAME, expected_version=tag)
        if not ok:
            os.remove(newfile)
            logging.error("REFUSING update %s: %s", tag, reason)
            return
        _swap_and_restart(current, newfile)
    except Exception as e:                              # noqa: BLE001
        logging.warning(f"update check failed: {e}")


def start_background():
    """Fire an immediate check, then re-check periodically. Best-effort, daemonized."""
    def loop():
        while True:
            _check_once()
            time.sleep(CHECK_EVERY_S)
    threading.Thread(target=loop, daemon=True).start()
