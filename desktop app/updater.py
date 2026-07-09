"""Self-update the Petabyte Desktop Agent from GitHub Releases.

On startup (and every few hours) the running .exe asks GitHub for the latest
release. If its tag is newer than the bundled VERSION, it downloads the attached
PetabyteAgent.exe and swaps itself in — Windows can't overwrite a running exe, so
a tiny detached .bat waits for exit, replaces the file, and relaunches.

No-ops unless running as a frozen Windows exe, so it never interferes with dev
runs or the Linux build check. Configure the source repo with PETABYTE_UPDATE_REPO
(default: BDR-Pro/lumaris_agent).
"""
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

REPO = os.getenv("PETABYTE_UPDATE_REPO", "BDR-Pro/lumaris_agent")
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY_S = int(os.getenv("PETABYTE_UPDATE_INTERVAL_S", str(6 * 3600)))
ASSET_NAME = "PetabyteAgent.exe"


def _ver(s: str):
    """Parse 'v1.2.3' -> (1,2,3); tolerant of junk."""
    out = []
    for part in s.lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def _latest():
    req = urllib.request.Request(
        LATEST_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "petabyte-agent"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    tag = data.get("tag_name", "")
    url = None
    for a in data.get("assets", []):
        if a.get("name", "").lower() == ASSET_NAME.lower():
            url = a.get("browser_download_url")
            break
    return tag, url


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
    logging.info("update downloaded — restarting to apply…")
    os._exit(0)


def _check_once():
    if not getattr(sys, "frozen", False) or os.name != "nt":
        return  # only the packaged Windows exe self-updates
    try:
        tag, url = _latest()
        if not tag or not url:
            return
        if _ver(tag) <= _ver(VERSION):
            logging.info(f"agent up to date (v{VERSION})")
            return
        logging.info(f"update {tag} available (current v{VERSION}) — downloading")
        current = sys.executable
        newfile = current + ".new"
        with urllib.request.urlopen(url, timeout=180) as r, open(newfile, "wb") as f:
            f.write(r.read())
        if os.path.getsize(newfile) < 1_000_000:      # sanity: real exe is tens of MB
            os.remove(newfile)
            logging.warning("downloaded update looked too small — skipped")
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
