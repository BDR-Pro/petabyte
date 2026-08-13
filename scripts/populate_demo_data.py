#!/usr/bin/env python3
"""populate_demo_data.py — fill the database with realistic, LABELLED demo data for UI/UX testing.

This is a superset of the investor demo (lumaris_api/demo.py): it runs that tested base seed
(sellers, verified supply, buyers, explainable routing, jobs, settlement, earnings) and then
ENRICHES it so the NEWER screens have data too:

  * spare-disk rental config + usage on some nodes  -> /seller disk UI, /disk/providers
  * idle-mining config + estimate on some nodes      -> idle earnings UI
  * a formed distributed cluster (ranks + rendezvous) -> /cluster, /jobs/manifest
  * running + migrated VMs with stable addresses      -> /console Compute tab, dynamic-DNS story

HONESTY (same rules as demo.py, enforced by demo_test.py):
  * Every base entity is stamped is_demo=True and reported SEPARATELY from real data; the UI badges
    it "Demo data".
  * The enrichments set only DISPLAY/STATUS fields (disk/idle config, cluster addresses, VM routes).
    They do NOT post any ledger settlement, so no fake money enters real revenue/earnings and
    "credited to date" stays honestly $0 until a real reconcile runs.
  * No fabricated partnerships or "production" claims.

Usage:
    python scripts/populate_demo_data.py            # wipe + seed + enrich (DATABASE_URL or demo.db)
    python scripts/populate_demo_data.py --keep     # enrich WITHOUT wiping (add to an existing DB)
    DATABASE_URL=sqlite:///./ui.db python scripts/populate_demo_data.py

Then serve the SAME DATABASE_URL and click around:
    cd lumaris_api && DATABASE_URL=sqlite:///../ui.db uvicorn main:app --reload
See docs/populate-data.md.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "lumaris_api"))
import demo  # the tested base seeder (register/prove/heartbeat/launch/jobs + is_demo stamping)

_DISK_PROVIDERS = ["storj", "btfs", "sia"]
_DISK_ALLOC = [500, 1000, 2000]


def _demo_specs(dbmod, s):
    return (s.query(dbmod.SellerSpec).filter(dbmod.SellerSpec.is_demo == True)  # noqa: E712
            .order_by(dbmod.SellerSpec.id).all())


def _first_demo_buyer(dbmod, s):
    return (s.query(dbmod.User)
            .filter(dbmod.User.is_demo == True,  # noqa: E712
                    dbmod.User.username.like(f"{demo.DEMO_PREFIX}%"),
                    dbmod.User.role == "buyer")
            .order_by(dbmod.User.id).first())


def enrich_disk_idle(dbmod):
    """Turn on spare-disk rental (varied providers/caps) and idle mining on a subset of nodes,
    with realistic usage + estimates. Display fields only — no ledger money."""
    out = {"disk": 0, "idle": 0}
    s = dbmod.SessionLocal()
    try:
        for i, sp in enumerate(_demo_specs(dbmod, s)):
            if i % 2 == 0:                      # every other node rents spare disk
                alloc = _DISK_ALLOC[i % len(_DISK_ALLOC)]
                sp.disk_enabled = True
                sp.disk_provider = _DISK_PROVIDERS[i % len(_DISK_PROVIDERS)]
                sp.disk_alloc_gb = alloc
                sp.disk_used_gb = round(alloc * 0.4, 1)
                sp.disk_est_daily_usd = round(alloc / 1000.0 * 1.5 / 30.0, 4)
                sp.disk_reported_at = dbmod._utcnow()
                out["disk"] += 1
            if i % 3 == 0:                      # some also idle-mine when unrented
                sp.idle_fallback = True
                sp.idle_algo = "daggerhashimoto"
                sp.idle_hashrate = round(60.0 + i * 7.5, 1)
                sp.idle_est_daily_usd = round(0.35 + i * 0.12, 4)
                sp.idle_reported_at = dbmod._utcnow()
                out["idle"] += 1
            s.add(sp)
        s.commit()
    except Exception as e:                      # noqa: BLE001 — best-effort enrichment
        print(f"  ! disk/idle enrichment skipped: {e}", file=sys.stderr)
    finally:
        s.close()
    return out


def seed_cluster(dbmod):
    """A formed distributed cluster (kind=distributed) across demo nodes, with every rank's
    rendezvous address registered so /cluster + /jobs/manifest render a ready cluster."""
    s = dbmod.SessionLocal()
    try:
        buyer = _first_demo_buyer(dbmod, s)
        specs = _demo_specs(dbmod, s)[:3]
        if not buyer or len(specs) < 2:
            return None
        job = dbmod.create_distributed_job(
            s, buyer,
            {"image": "pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime",
             "command": "torchrun train.py --epochs 3", "selftest": False,
             "note": "demo cluster — no buyer code executed"},
            world_size=len(specs), backend="nccl")
        for idx, _sp in enumerate(specs):
            seg = dbmod.add_job_segment(s, job, idx, None, idx, idx)
            dbmod.register_peer(s, seg, f"10.8.0.{idx + 1}", 29500, slots=1)
        dbmod.set_rendezvous(s, job, "10.8.0.1", 29500)   # rank 0 is the master
        return job.id
    except Exception as e:                      # noqa: BLE001
        print(f"  ! cluster enrichment skipped: {e}", file=sys.stderr)
        return None
    finally:
        s.close()


def seed_vms(dbmod):
    """A couple of rentable VMs with STABLE addresses: one running, one that 'migrated' nodes
    (its address unchanged) — so the VM UI + the dynamic-DNS story have live content."""
    ids = []
    s = dbmod.SessionLocal()
    try:
        buyer = _first_demo_buyer(dbmod, s)
        specs = _demo_specs(dbmod, s)
        booking = (s.query(dbmod.Booking).filter(dbmod.Booking.buyer_id == buyer.id).first()
                   if buyer else None)
        if not buyer or not booking or len(specs) < 2:
            return ids
        plans = [("comfyui", 8188, specs[0], "10.0.0.1", 40001, 0),
                 ("jupyter", 8888, specs[1], "10.0.0.2", 40002, 1)]
        for template, port, sp, ip, tport, migrations in plans:
            vm = dbmod.create_vm_route(s, buyer.id, booking.id, template, sp.id,
                                       app_port=port, hourly_rate=sp.price_per_hour, hours=24)
            dbmod.register_vm_tunnel(s, vm.id, sp.id, tport, ip)   # -> running
            if migrations:
                vm.migrations = migrations
                s.add(vm)
                dbmod.vm_event(s, vm.id, "migrated",
                               "demo: node changed; address unchanged")
                s.commit()
            ids.append(vm.id)
    except Exception as e:                      # noqa: BLE001
        print(f"  ! VM enrichment skipped: {e}", file=sys.stderr)
    finally:
        s.close()
    return ids


def main(argv):
    keep = "--keep" in argv
    demo._bootstrap_env()
    from fastapi.testclient import TestClient
    import db as dbmod
    import main as app_main

    if not keep:
        demo.wipe(dbmod)
    client = TestClient(app_main.app)
    summary = demo.seed(client, dbmod)          # tested base (marketplace + jobs + settlement)

    disk = enrich_disk_idle(dbmod)
    cluster_id = seed_cluster(dbmod)
    vm_ids = seed_vms(dbmod)
    demo._stamp_demo(dbmod)                      # keep any newly-touched demo rows labelled

    demo._print_info(summary)
    print("  UI/UX enrichment (all labelled demo, no fabricated earnings):")
    print(f"    spare-disk rental ... {disk['disk']} node(s) contributing  ->  /seller disk UI, /disk/providers")
    print(f"    idle mining ......... {disk['idle']} node(s)                ->  idle earnings UI")
    print(f"    distributed cluster . job #{cluster_id}                     ->  /cluster, /jobs/manifest/{cluster_id}")
    print(f"    rentable VMs ........ {len(vm_ids)} (1 running, 1 migrated)  ->  /console VM tab (stable address)")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
