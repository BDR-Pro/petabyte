#!/usr/bin/env python3
"""Standalone heartbeat reaper. Run as its own service so stale-spec reaping
happens once, not once per gunicorn worker. Set REAPER_DISABLED=true on the
web service when this is running."""
import os, time
from db import SessionLocal, reap_stale_specs, HEARTBEAT_TIMEOUT_S

INTERVAL = int(os.getenv("REAPER_INTERVAL_S", "20"))


def main():
    print(f"reaper started (interval={INTERVAL}s, timeout={HEARTBEAT_TIMEOUT_S}s)", flush=True)
    while True:
        try:
            db = SessionLocal()
            n = reap_stale_specs(db, HEARTBEAT_TIMEOUT_S)
            db.close()
            if n:
                print(f"reaped {n} stale spec(s)", flush=True)
        except Exception as e:
            print("reaper error:", e, flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
