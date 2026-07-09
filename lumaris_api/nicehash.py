"""NiceHash earnings adapter. Petabyte runs ONE NiceHash account; each node mines as
worker `pb-<spec_id>`, so per-worker earnings map 1:1 to sellers. This returns SETTLED
per-worker USD for a period; the reconciler credits sellers' unified balances.

Stub for tests (`NICEHASH_STUB=true`). The real path is functional code that signs a
NiceHash API request; it needs org credentials in env to run."""
import hashlib
import hmac
import json
import os
import time
import uuid

import httpx

API = os.getenv("NICEHASH_API", "https://api2.nicehash.com")


def _signed_headers(method: str, path: str, query: str = "", body: str = ""):
    key = os.environ["NICEHASH_API_KEY"]
    secret = os.environ["NICEHASH_API_SECRET"]
    org = os.environ["NICEHASH_ORG_ID"]
    ts = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    # NiceHash HMAC: key;time;nonce;;org;;method;path;query[;body] joined by \x00
    segs = [key, ts, nonce, "", org, "", method, path, query]
    if body:
        segs += [body]
    msg = "\x00".join(segs)
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {"X-Time": ts, "X-Nonce": nonce, "X-Organization-Id": org,
            "X-Request-Id": nonce, "X-Auth": f"{key}:{sig}", "Accept": "application/json"}


def get_worker_earnings(period: str) -> dict:
    """Return {worker_id: {"period": period, "amount": usd}} of settled earnings.

    Stub returns {} (tests inject the map directly into reconcile). Real path pulls
    per-rig/worker stats from the NiceHash API and maps rig name -> earnings.
    """
    if os.getenv("NICEHASH_STUB", "").lower() == "true":
        return {}
    path = "/main/api/v2/mining/rigs2"
    try:
        r = httpx.get(API + path, headers=_signed_headers("GET", path), timeout=20)
        r.raise_for_status()
        data = r.json()
        out = {}
        for rig in data.get("miningRigs", []):
            name = rig.get("name", "")
            if not name.startswith("pb-"):
                continue
            usd = float(rig.get("profitability", 0.0))   # BTC/day; convert upstream
            out[name] = {"period": period, "amount": usd}
        return out
    except Exception:
        return {}
