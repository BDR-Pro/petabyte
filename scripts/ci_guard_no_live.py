#!/usr/bin/env python3
"""CI money-safety guard: FAIL the build if the environment could move REAL money.

A misconfigured Secret/Variable, a bad merge, or a copy-pasted production key must never
let CI touch live money. This aborts when a LIVE Stripe key or a live-payout switch is
present. It prints ONLY offending variable NAMES and reasons — never a secret value.

Test keys (sk_test_/pk_test_) and webhook secrets (whsec_, identical shape for test+live)
are allowed. Exit 0 = safe (test mode only). Exit 1 = live money possible -> abort.

Run: python scripts/ci_guard_no_live.py
"""
import os
import re
import sys

# LIVE Stripe key prefixes: secret (sk), restricted (rk), publishable (pk).
_LIVE_KEY = re.compile(r"\b(?:sk|rk|pk)_live_[A-Za-z0-9]")
_TRUE = {"1", "true", "yes", "on"}


def find_problems(env: dict) -> list[str]:
    problems = []
    for name, value in env.items():
        if value and _LIVE_KEY.search(value):
            problems.append(f"{name}: contains a LIVE Stripe key (…_live_…)")
    for flag in ("PAYMENTS_LIVE_ENABLED", "STRIPE_ALLOW_LIVE"):
        if (env.get(flag) or "").strip().lower() in _TRUE:
            problems.append(f"{flag} is on (live-money switch)")
    for mode_var in ("STRIPE_MODE", "PAYMENTS_MODE"):
        if (env.get(mode_var) or "").strip().lower() == "live":
            problems.append(f"{mode_var}=live")
    return problems


def main() -> int:
    problems = find_problems(os.environ)
    if problems:
        print("::error::CI money-safety guard TRIPPED — refusing to run tests that could move "
              "REAL money:", file=sys.stderr)
        for p in problems:
            print(f"::error::  - {p}", file=sys.stderr)
        print("CI must use Stripe TEST mode only. Remove any live key / live switch from the "
              "CI environment before re-running.", file=sys.stderr)
        return 1
    print("CI money-safety guard: OK (no live Stripe key or live-money switch present).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
