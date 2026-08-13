"""Petabyte Desktop Agent — entry point.

A double-clickable desktop app that:
  1. always launches the local dashboard (http://127.0.0.1:5000), even before the
     node is configured — so the seller can paste their API key + Spec ID in the UI;
  2. starts the agent loop (heartbeat + job polling + attestation) automatically as
     soon as the config is complete, and never before (task_fetcher hard-exits when
     unconfigured, so we import it lazily);
  3. opens the dashboard in the default browser.

Build to a Windows .exe with:  python build_exe.py   (see BUILD.md)
"""
import logging
import os
import sys
import threading
import time
import webbrowser

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import cli_ui
import agent_cli

agent_cli.PRODUCT = "Petabyte Desktop Agent"

# Sensible default so an un-configured launch still points at the right API.
os.environ.setdefault("PETABYTE_API_URL", "https://petabyte.market")


def _configure_logging():
    """Set up logging when the app actually runs — NOT at import, so `doctor --json`
    and `--version` keep stdout clean (no stray httpx 'HTTP Request' log lines)."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler("petabyte_agent.log")],
    )

_started = threading.Event()


def _start_agent_once():
    """Import + launch the agent loop exactly once, when config is ready."""
    if _started.is_set() or not configured():
        return
    _started.set()
    logging.info("Configuration detected — starting Petabyte agent…")
    try:
        import importlib
        import task_fetcher
        importlib.reload(task_fetcher)          # pick up env set via the UI
        threading.Thread(target=task_fetcher.run_agent, daemon=True).start()
        agent_status["status"] = "running"
    except SystemExit as e:                     # unconfigured guard tripped
        logging.error(f"agent not started: {e}")
        agent_status["status"] = "needs-config"
        _started.clear()
    except Exception as e:                      # noqa: BLE001
        logging.error(f"agent failed to start: {e}")
        agent_status["status"] = "error"
        _started.clear()


def _supervisor():
    """Wait for config (from env or the UI), then start the agent."""
    while not _started.is_set():
        _start_agent_once()
        time.sleep(2)


def main():
    # --help / --version / doctor run before the dashboard launches (and before any
    # config is required), so the packaged .exe answers them cleanly.
    if agent_cli.handle_cli(sys.argv[1:]):
        return

    # ui is safe to import unconfigured (it never imports task_fetcher at load time);
    # done here so the CLI paths above stay fast and dependency-light.
    _configure_logging()
    global run_ui, agent_status, configured
    from ui import run_ui, agent_status, configured

    out = cli_ui.out
    agent_cli.banner(out, product="Petabyte Desktop Agent", url=os.getenv("PETABYTE_API_URL"))
    out.line(out.dim("  dashboard  ") + "http://127.0.0.1:5000")
    out.blank()

    # Best-effort self-update (only active in the packaged Windows .exe).
    try:
        import updater
        updater.start_background()
    except Exception as e:  # noqa: BLE001
        logging.debug(f"updater unavailable: {e}")
    threading.Thread(target=run_ui, args=("127.0.0.1", 5000, False), daemon=True).start()
    threading.Thread(target=_supervisor, daemon=True).start()
    logging.info("Petabyte Desktop Agent — dashboard at http://127.0.0.1:5000")
    if not configured():
        out.warn("Not configured yet — open the dashboard to add your API key + Spec ID.")
    try:
        webbrowser.open("http://127.0.0.1:5000")
    except Exception:
        pass
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down…")
        sys.exit(0)


if __name__ == "__main__":
    main()
