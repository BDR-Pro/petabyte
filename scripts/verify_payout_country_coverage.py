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


def _print_priority(m):
    print("=" * 72)
    print(f"  Petabyte priority-market payout capability "
          f"(platform {m['platform_country']}, verified {m['verified_at']})")
    print("=" * 72)
    print(f"  {'CC':<4}{'COUNTRY':<18}{'RAIL':<18}{'CCY':<6}{'STATUS'}")
    print("  " + "-" * 68)
    for c in m["countries"]:
        ccy = ",".join(c["settlement_currencies"][:2]) or "-"
        rail = c["rail"] or "-"
        print(f"  {c['country_code']:<4}{(c['country_name'] or '')[:17]:<18}"
              f"{rail:<18}{ccy:<6}{c['status']}")
    print("  " + "-" * 68)
    print(f"  priority markets:        {m['priority_count']}")
    print(f"  ACTIVE today (payable):  {m['active_today_count']}")
    print(f"  capable (rail on file):  {m['capable_count']}")
    print(f"  not supported yet:       {m['not_supported_count']}")
    print(f"  blocked (sanctioned):    {m['blocked_count']}")
    print("  status breakdown:")
    for k, v in sorted(m["status_buckets"].items()):
        print(f"    - {k}: {len(v)}  ({', '.join(v)})")
    print("\n  NOTE: 'capable' means a rail exists on file, NOT that it pays today. Only "
          "ACTIVE\n  countries are payable now; the shipped dataset is honestly 0 until "
          "a real\n  end-to-end payout is verified per country.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--priority", action="store_true",
                    help="verify the priority-market watch list (per-country capability) "
                         "instead of the global coverage target")
    args = ap.parse_args()

    if args.priority:
        m = cap.priority_capability_matrix()
        # honesty invariant: every priority country resolves to a known, consistent status
        # and no country is falsely marked payable without passing the strict active rule.
        _valid = {"active", "pending_provider_approval", "preview", "planned",
                  "not_implemented", "not_supported", "blocked_sanctioned", "unknown"}
        bad = [c for c in m["countries"] if c["status"] not in _valid
               or c["status"] == "unknown"
               or (c["active_today"] and c["status"] != "active")]
        if args.json:
            print(json.dumps(m, indent=2))
        else:
            _print_priority(m)
        if bad:
            print(f"\nRESULT: INCONSISTENT — {len(bad)} priority country(ies) resolved to "
                  f"an unknown/contradictory status: {[c['country_code'] for c in bad]}",
                  file=sys.stderr)
            return EXIT_ERROR
        print(f"\nRESULT: OK — {m['priority_count']} priority markets verified "
              f"({m['active_today_count']} active today, {m['capable_count']} capable, "
              f"{m['not_supported_count']} not supported, {m['blocked_count']} blocked).")
        return EXIT_OK

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


EXIT_OK = 0          # target met
EXIT_SHORTFALL = 1   # EXPECTED honest shortfall (informational; not a verifier failure)
EXIT_ERROR = 2       # unexpected failure: malformed dataset, import error, regression

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:                       # distinguish a real failure from a shortfall
        print(f"\nVERIFIER ERROR (exit {EXIT_ERROR}): {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
