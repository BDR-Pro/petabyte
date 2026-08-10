#!/usr/bin/env python3
"""sentry_selftest.py — deliberately send ONE test event to Sentry to verify the pipeline.

Drives the REAL configuration path (env -> observability.init_observability -> sentry_sdk.init)
and, with --send, emits a single benign event so you can confirm it lands in the Sentry project.
Used by the TEST GitHub Environment workflow (.github/workflows/sentry-verify-test.yml).

It NEVER prints the DSN or any secret. Unit tests (sentry_test.py) do NOT call this — they mock
the SDK and make no network calls; only this script, run in the TEST environment, sends a real
event.

  python scripts/sentry_selftest.py           # dry-run: report whether Sentry would initialise
  python scripts/sentry_selftest.py --send     # emit exactly one test event (needs SENTRY_DSN)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "lumaris_api"))
import observability as o  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify Sentry by sending one test event.")
    ap.add_argument("--send", action="store_true",
                    help="actually emit ONE test event (otherwise dry-run)")
    args = ap.parse_args(argv)

    o.init_observability("petabyte-sentry-selftest")
    h = o.health()["sentry"]
    dsn_present = bool(os.getenv("SENTRY_DSN", "").strip())
    # Report status WITHOUT ever printing the DSN value.
    print(f"sentry: dsn_present={dsn_present} active={h['active']} "
          f"environment={h['environment']} release={o.SENTRY_RELEASE}")

    if not args.send:
        print("dry-run — pass --send to emit one test event")
        return 0
    if not h["active"]:
        print("::error::--send requested but Sentry is NOT active. Is SENTRY_DSN set for this "
              "environment (GitHub TEST env variable), and SENTRY_ENABLED != false?", file=sys.stderr)
        return 2

    event_id = o.capture_message(
        "Petabyte Sentry selftest — deliberate test event from CI (TEST environment)",
        level="error", selftest="true", source="ci", release=o.SENTRY_RELEASE)
    try:
        import sentry_sdk
        sentry_sdk.flush(timeout=10)
    except Exception:  # noqa: BLE001 — flush is best-effort
        pass
    if not event_id:
        print("::error::Sentry was active but capture returned no event id", file=sys.stderr)
        return 3
    print(f"sent test event id={event_id} — check the Sentry TEST project "
          f"(environment={h['environment']}, release={o.SENTRY_RELEASE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
