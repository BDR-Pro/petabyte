#!/usr/bin/env python3
"""Verify seller-payout country coverage from the normalized capability dataset.

Prints the honest breakdown and EXITS NON-ZERO when fewer than TARGET countries have
genuinely verified, implemented, approved and active coverage. It counts ONLY rows that
are active + implemented + approved + not sanctioned — an unimplemented adapter or an
unapproved preview product never counts.

Do NOT edit the dataset to force this to pass; the objective is genuine reach.
Usage: python scripts/verify_payout_country_coverage.py [--target 100]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "lumaris_api"))
import payout_capabilities as cap   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    s = cap.coverage_summary()
    if args.json:
        print(json.dumps(s, indent=2))
    else:
        print("=" * 64)
        print(f"  Petabyte seller-payout coverage (platform {s['platform_country']}, "
              f"verified {s['verified_at']})")
        print("=" * 64)
        print(f"  ACTIVE (verified, implemented, approved):  {s['active_count']}")
        print(f"    - bank-payout countries:                 {len(s['active_bank_countries'])}")
        print(f"    - stablecoin-only countries:             {len(s['active_stablecoin_only_countries'])}")
        print(f"    - multi-rail countries:                  {len(s['multi_rail_countries'])}")
        print(f"  PENDING_PROVIDER_APPROVAL:                 {len(s['pending_provider_approval_countries'])}")
        print(f"  PREVIEW:                                   {len(s['preview_countries'])}")
        print(f"  PLANNED:                                   {len(s['planned_countries'])}")
        print(f"  NOT_IMPLEMENTED:                           {len(s['not_implemented_countries'])}")
        print(f"  BLOCKED (sanctioned):                      {len(s['blocked_sanctioned_countries'])}")
        print("  sources:")
        for k, v in s["sources"].items():
            print(f"    - {k}: {v}")
        print("-" * 64)
        print(f"  TARGET active countries: {args.target}")

    if s["active_count"] < args.target:
        gap = args.target - s["active_count"]
        print(f"\nRESULT: SHORTFALL — {s['active_count']}/{args.target} active "
              f"({gap} to go). Close the gap only via real provider approvals + "
              f"implemented rails; do NOT edit the dataset to pass.")
        return 1
    print(f"\nRESULT: OK — {s['active_count']}/{args.target} active countries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
