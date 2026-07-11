#!/usr/bin/env python3
"""Standalone heartbeat reaper. Run as its own service so stale-spec reaping
happens once, not once per gunicorn worker. Set REAPER_DISABLED=true on the
web service when this is running."""
import os, time
from db import SessionLocal, reap_and_failover, meter_and_expire, reprice_specs, HEARTBEAT_TIMEOUT_S

INTERVAL = int(os.getenv("REAPER_INTERVAL_S", "20"))


def main():
    print(f"reaper started (interval={INTERVAL}s, timeout={HEARTBEAT_TIMEOUT_S}s)", flush=True)
    while True:
        try:
            db = SessionLocal()
            n, migrated = reap_and_failover(db, HEARTBEAT_TIMEOUT_S)
            stopped = meter_and_expire(db)
            repriced = reprice_specs(db)
            db.close()
            if n or migrated or stopped or repriced:
                print(f"reaped {n}, migrated {migrated}, auto-stopped {stopped}, "
                      f"repriced {repriced}", flush=True)
        except Exception as e:
            print("reaper error:", e, flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
