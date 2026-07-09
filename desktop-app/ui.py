"""Petabyte Desktop Agent — local dashboard (NiceHash-style).

Unlike the headless agent, this UI must run even before the node is configured,
so a seller can launch the .exe, paste their API key + Spec ID, and go. It reads
config from the environment only (it never imports task_fetcher at load time,
because task_fetcher intentionally hard-exits when unconfigured). Saving config
writes it to both the process environment and a local .env; the desktop
supervisor (petabyte_desktop.py) then starts the agent loop automatically.
"""
from flask import Flask, render_template, jsonify, request
import threading
import time
import logging
import os

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None

DEFAULT_API_URL = "https://petabyte.market"

def _cfg():
    return {
        "api_url": os.getenv("PETABYTE_API_URL", DEFAULT_API_URL),
        "api_key": os.getenv("PETABYTE_API_KEY", ""),
        "spec_id": os.getenv("PETABYTE_SPEC_ID", ""),
    }

def configured():
    c = _cfg()
    return bool(c["api_key"] and c["spec_id"])

app = Flask(__name__)
app.config["SECRET_KEY"] = "petabyte-agent-secret-key"

# Shared status dict — task_fetcher._set_ui() writes into this.
agent_status = {
    "agent_id": _cfg()["spec_id"] or "unconfigured",
    "status": "configured" if configured() else "needs-config",
    "current_task": None,
    "tasks_completed": 0,
    "tasks_failed": 0,
    "uptime": 0,
    "last_heartbeat": None,
    "api_connected": False,
}

start_time = time.time()


def _persist_env(updates: dict):
    """Write key=value pairs into a local .env next to the app (best effort)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    existing = {}
    try:
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
    except Exception:
        pass
    existing.update({k: v for k, v in updates.items() if v is not None})
    try:
        with open(path, "w", encoding="utf-8") as f:
            for k, v in existing.items():
                f.write(f"{k}={v}\n")
    except Exception as e:
        logging.warning(f"could not persist .env: {e}")


def update_status():
    """Poll API connectivity + refresh uptime."""
    global agent_status
    while True:
        c = _cfg()
        if httpx and c["api_key"]:
            try:
                r = httpx.get(f"{c['api_url']}/verify_api_key",
                              headers={"X-API-KEY": c["api_key"]}, timeout=5)
                agent_status["api_connected"] = r.status_code == 200
            except Exception:
                agent_status["api_connected"] = False
        else:
            agent_status["api_connected"] = False
        agent_status["uptime"] = int(time.time() - start_time)
        agent_status["last_heartbeat"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if agent_status["status"] == "needs-config" and configured():
            agent_status["status"] = "starting"
        time.sleep(5)


threading.Thread(target=update_status, daemon=True).start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def get_status():
    return jsonify(agent_status)


@app.route("/api/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        updates = {}
        if data.get("api_key"):
            os.environ["PETABYTE_API_KEY"] = data["api_key"].strip()
            updates["PETABYTE_API_KEY"] = os.environ["PETABYTE_API_KEY"]
        # the dashboard field is labelled Spec ID; accept either key for compatibility
        spec = data.get("spec_id") or data.get("agent_id")
        if spec:
            os.environ["PETABYTE_SPEC_ID"] = str(spec).strip()
            updates["PETABYTE_SPEC_ID"] = os.environ["PETABYTE_SPEC_ID"]
            agent_status["agent_id"] = os.environ["PETABYTE_SPEC_ID"]
        if data.get("api_url"):
            os.environ["PETABYTE_API_URL"] = data["api_url"].strip()
            updates["PETABYTE_API_URL"] = os.environ["PETABYTE_API_URL"]
        _persist_env(updates)
        return jsonify({"status": "ok", "configured": configured()})
    c = _cfg()
    return jsonify({
        "api_key": (c["api_key"][:10] + "…") if len(c["api_key"]) > 10 else c["api_key"],
        "agent_id": c["spec_id"],
        "spec_id": c["spec_id"],
        "api_url": c["api_url"],
        "configured": configured(),
    })


def run_ui(host="127.0.0.1", port=5000, debug=False):
    logging.info(f"Starting Petabyte Agent UI on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run_ui()
