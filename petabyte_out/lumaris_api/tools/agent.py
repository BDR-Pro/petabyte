#!/usr/bin/env python3
"""Seller node heartbeat agent. Keeps a spec 'online' so it stays bookable.

Usage:
  API_BASE=http://localhost:8000 API_KEY=<key> SPEC_ID=1 python tools/agent.py
"""
import os, time, sys, urllib.request, json

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
API_KEY = os.getenv("API_KEY")
SPEC_ID = int(os.getenv("SPEC_ID", "0"))
INTERVAL = int(os.getenv("INTERVAL", "15"))

if not API_KEY or not SPEC_ID:
    sys.exit("set API_KEY and SPEC_ID env vars")


def beat():
    req = urllib.request.Request(
        f"{API_BASE}/heartbeat",
        data=json.dumps({"spec_id": SPEC_ID}).encode(),
        headers={"Content-Type": "application/json", "X-API-KEY": API_KEY},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode()


print(f"heartbeating spec {SPEC_ID} -> {API_BASE} every {INTERVAL}s")
while True:
    try:
        code, body = beat()
        print(time.strftime("%H:%M:%S"), code, body)
    except Exception as e:
        print(time.strftime("%H:%M:%S"), "ERROR", e)
    time.sleep(INTERVAL)
