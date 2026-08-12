#!/usr/bin/env python3
"""cluster_demo.py — drive a DISTRIBUTED cluster demo from the BUYER side.

One buyer, N seller nodes (e.g. two GPU VMs), one job across all of them. This is the
buyer-side companion to `buyer_probe.py`, for the multi-node story: it uses ONLY the public API
(the same endpoints the /cluster page calls), logs in as the buyer, launches a cluster, and
watches it form and complete over the real control plane + execution loop.

    login → /distributed/availability → POST /distributed → /jobs/{id}/cluster
          → poll /jobs/manifest/{id} until every rank finishes (or one fails)

Two execution modes:
  * --selftest  (default): each rank runs the BUILT-IN cross-process all-reduce — no GPU, no
    image, no NCCL. The reliable live proof that the N nodes actually talk to each other and
    compute the correct global reduction. Best for a stage demo.
  * --image/--command: a REAL training run — each node runs your container under torchrun wired
    to the master. More impressive; needs matching CUDA images + the WireGuard mesh (--vpn).

Nothing here is faked: the seller VMs' agents do the execution and report SIGNED results; this
script only drives the buyer and reports what the server says. Secrets: the buyer password is
read with getpass (never echoed, never in argv).

Examples:
  # two GPU VMs, built-in all-reduce self-test (recommended live demo)
  python3 scripts/e2e/cluster_demo.py --api-url https://petabyte.market \
      --buyer testUserBuyer --world-size 2 --selftest

  # a real 2-node torchrun training run over the VPN mesh
  python3 scripts/e2e/cluster_demo.py --buyer testUserBuyer --world-size 2 --vpn \
      --image pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime \
      --command "torchrun train.py --epochs 3"
"""
import argparse
import getpass
import os
import sys
import time

import httpx

TIMEOUT = 20.0


def _die(msg, code=1):
    print(f"\nERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _fmt_usd(v):
    try:
        return f"${float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def main():
    ap = argparse.ArgumentParser(description="Drive a distributed cluster demo (buyer side).")
    ap.add_argument("--api-url", default=os.getenv("PETABYTE_API_URL", "https://petabyte.market"))
    ap.add_argument("--buyer", default=os.getenv("BUYER_USER", "testUserBuyer"))
    ap.add_argument("--password", default=os.getenv("BUYER_PASS"),
                    help="Buyer password (else prompted; never pass on a shared shell).")
    ap.add_argument("--world-size", type=int, default=2, help="ranks = number of distinct nodes")
    ap.add_argument("--hours", type=int, default=1)
    ap.add_argument("--backend", default="nccl", choices=["nccl", "gloo"])
    ap.add_argument("--selftest", action="store_true",
                    help="Run the built-in cluster all-reduce self-test (no image/GPU needed).")
    ap.add_argument("--image", default=None, help="Training container image (real run).")
    ap.add_argument("--command", default=None, help="torchrun target, e.g. 'train.py --epochs 3'.")
    ap.add_argument("--vpn", action="store_true", help="Provision a WireGuard tunnel into the cluster.")
    ap.add_argument("--gpu-class", default=None)
    ap.add_argument("--region", default=None)
    ap.add_argument("--poll-timeout", type=int, default=600, help="seconds to wait for completion")
    args = ap.parse_args()

    if not args.selftest and not args.image:
        _die("choose an execution mode: --selftest, or --image (+ --command) for a real run.")

    base = args.api_url.rstrip("/")
    password = args.password or getpass.getpass(f"Password for {args.buyer}: ")

    with httpx.Client(timeout=TIMEOUT) as c:
        # 1) login (OAuth2 password grant) -> bearer token
        r = c.post(f"{base}/login", data={"username": args.buyer, "password": password})
        if r.status_code != 200:
            _die(f"login failed ({r.status_code}): {r.text[:200]}")
        tok = r.json().get("access_token")
        H = {"Authorization": f"Bearer {tok}"}
        print(f"✓ logged in as {args.buyer}")

        # 2) availability — how big a cluster can form right now (distinct nodes = distinct owners)
        av = c.get(f"{base}/distributed/availability").json()
        n_avail = av.get("available_nodes", 0)
        print(f"  available distinct nodes: {n_avail} "
              f"(max cluster {av.get('max_cluster')}, ~{_fmt_usd(av.get('est_price_per_hour'))}/node/hr)")
        if n_avail < args.world_size:
            print(f"  ! only {n_avail} distinct nodes are online + payout-ready, but you asked for "
                  f"{args.world_size}.\n    Each rank lands on a DISTINCT owner — bring "
                  f"{args.world_size} seller accounts online (one per VM).")

        # 3) launch the cluster
        body = {"world_size": args.world_size, "hours": args.hours, "backend": args.backend,
                "vpn": bool(args.vpn)}
        if args.selftest:
            body["selftest"] = True
        else:
            body["image"] = args.image
            if args.command:
                body["command"] = args.command
        for k in ("gpu_class", "region"):
            v = getattr(args, k)
            if v:
                body[k] = v
        mode = "SELF-TEST (built-in all-reduce)" if args.selftest else f"REAL run: {args.image}"
        print(f"\n→ launching {args.world_size}-node cluster · {mode} · backend {args.backend}"
              f"{' · VPN' if args.vpn else ''}")
        r = c.post(f"{base}/distributed", headers=H, json=body)
        if r.status_code != 200:
            try:
                j = r.json()
                err = (j.get("error") or {})
                code = err.get("code") or (j.get("detail", {}).get("code")
                                           if isinstance(j.get("detail"), dict) else None)
                msg = err.get("message") or (j.get("detail") if isinstance(j.get("detail"), str)
                                             else j)
            except Exception:
                code, msg = None, r.text[:200]
            hint = ""
            if code == "INSUFFICIENT_DISTINCT_NODES":
                hint = ("\n  Fix: bring more seller accounts online (one rank per owner). "
                        "Two VMs must be TWO seller accounts, not one.")
            elif code == "CLUSTER_BOOKING_FAILED":
                hint = ("\n  Fix: fund the buyer wallet — every rank is escrowed up-front, "
                        "all-or-nothing. Nothing was charged.")
            _die(f"/distributed refused ({r.status_code}, {code}): {msg}{hint}")
        j = r.json()
        job_id = j["job_id"]
        print(f"✓ cluster job #{job_id} formed · world_size={j['world_size']} · "
              f"escrowed ≈ {_fmt_usd(j.get('estimated_cost'))} for {j['hours']}h")
        for rk in j.get("ranks", []):
            tag = " (master)" if rk.get("is_master") else ""
            print(f"    rank {rk['rank']}{tag}: node {rk['spec_id']} · task {rk['task_id']} · "
                  f"{_fmt_usd(rk.get('price_per_hour'))}/hr")

        # 4) the cluster as the artifacts an existing scheduler consumes (Petabyte = another provider)
        cl = c.get(f"{base}/jobs/{job_id}/cluster", headers=H)
        if cl.status_code == 200 and cl.json().get("launch"):
            L = cl.json()["launch"]
            print("\n  export to your scheduler (once ranks register their addresses):")
            print(f"    hostfile : GET {base}/jobs/{job_id}/hostfile")
            if L.get("torchrun"):
                print(f"    torchrun : {L['torchrun']}")
            if L.get("mpirun"):
                print(f"    mpirun   : {L['mpirun']}")
        if args.vpn and j.get("vpn_config_url"):
            print(f"    VPN cfg  : GET {base}{j['vpn_config_url']} (WireGuard client config)")

        # 5) poll the manifest until every rank finishes (or one fails → gang failure)
        print(f"\n… waiting for the cluster to execute (poll {base}/jobs/manifest/{job_id})")
        deadline = time.time() + args.poll_timeout
        last = None
        while time.time() < deadline:
            m = c.get(f"{base}/jobs/manifest/{job_id}", headers=H).json()
            done = sum(1 for s in m.get("segments", []) if s.get("status") == "done")
            snap = (m.get("status"), done, m.get("rendezvous_ready"))
            if snap != last:
                rz = "ready" if m.get("rendezvous_ready") else "forming"
                print(f"    status={m['status']} · ranks done {done}/{m.get('total_segments')} "
                      f"· rendezvous {rz}")
                last = snap
            if m.get("status") in ("complete", "failed"):
                break
            time.sleep(3)
        else:
            _die(f"timed out after {args.poll_timeout}s waiting for job #{job_id}", code=2)

        # 6) summary
        m = c.get(f"{base}/jobs/manifest/{job_id}", headers=H).json()
        print("\n" + "=" * 60)
        if m["status"] == "complete":
            print(f"✓ CLUSTER COMPLETE — job #{job_id}: every rank ran and reported a signed result.")
            for s in m.get("segments", []):
                print(f"    rank {s['idx']}: {s['status']} · {s.get('output_ref') or '—'}")
            print("=" * 60)
            return 0
        print(f"✗ CLUSTER FAILED — job #{job_id}: a rank did not complete (gang semantics: one "
              f"dead rank fails the whole run).")
        for s in m.get("segments", []):
            print(f"    rank {s['idx']}: {s['status']}")
        print("=" * 60)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
