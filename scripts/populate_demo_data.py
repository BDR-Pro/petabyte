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


def _has_cols(model, *names):
    """True only if the mapped table actually has these columns. Lets this script run on
    an older schema (a branch without the disk-rental columns, say) without silently
    'succeeding' at writes that persist nothing — the honesty rule in the docstring."""
    cols = {c.name for c in model.__table__.columns}
    return all(n in cols for n in names)


def _has_fns(dbmod, *names):
    return all(hasattr(dbmod, n) for n in names)


def _demo_specs(dbmod, s):
    return (s.query(dbmod.SellerSpec).filter(dbmod.SellerSpec.is_demo == True)  # noqa: E712
            .order_by(dbmod.SellerSpec.id).all())


def _first_demo_buyer(dbmod, s):
    return (s.query(dbmod.User)
            .filter(dbmod.User.is_demo == True,  # noqa: E712
                    dbmod.User.username.like(f"{demo.DEMO_PREFIX}%"),
                    dbmod.User.role == "buyer")
            .order_by(dbmod.User.id).first())


def _demo_data_present(dbmod):
    """True when the DB already holds labelled demo users. Used by --keep so we can enrich
    an existing seed WITHOUT re-running the base seed (which re-registers the demo accounts
    and raises a duplicate-registration error)."""
    s = dbmod.SessionLocal()
    try:
        return (s.query(dbmod.User)
                .filter(dbmod.User.is_demo == True,  # noqa: E712
                        dbmod.User.username.like(f"{demo.DEMO_PREFIX}%"))
                .count() > 0)
    except Exception:                               # noqa: BLE001 — no schema yet == not present
        return False
    finally:
        s.close()


def _summary_from_db(dbmod):
    """Reconstruct the operator summary from the demo rows already in the DB — used by --keep
    when the base seed is skipped, so _print_info can still report honest counts."""
    s = dbmod.SessionLocal()
    try:
        demo_user_ids = [u.id for u in s.query(dbmod.User).filter(
            dbmod.User.is_demo == True,             # noqa: E712
            dbmod.User.username.like(f"{demo.DEMO_PREFIX}%")).all()]
        n_users = len(demo_user_ids)
        n_specs = s.query(dbmod.SellerSpec).filter(dbmod.SellerSpec.is_demo == True).count()  # noqa: E712
        n_bookings = s.query(dbmod.Booking).filter(dbmod.Booking.is_demo == True).count()  # noqa: E712

        def _jobs(status):
            if not demo_user_ids:
                return 0
            return (s.query(dbmod.Task)
                    .filter(dbmod.Task.buyer_id.in_(demo_user_ids),
                            dbmod.Task.status == status).count())

        completed, running, failed = _jobs("completed"), _jobs("running"), _jobs("failed")
    finally:
        s.close()
    return {
        "sellers": [demo.DEMO_PREFIX + x["user"] for x in demo.DEMO_SELLERS],
        "buyers": [demo.DEMO_PREFIX + x["user"] for x in demo.DEMO_BUYERS],
        "password": demo.DEMO_PASSWORD,
        "counts": {"demo_users": n_users, "demo_specs": n_specs,
                   "demo_bookings": n_bookings, "jobs_completed": completed,
                   "jobs_running": running, "jobs_failed": failed},
    }


def enrich_disk_idle(dbmod):
    """Turn on spare-disk rental (varied providers/caps) and idle mining on a subset of nodes,
    with realistic usage + estimates. Display fields only — no ledger money.

    Each half is applied only if the schema actually has EVERY column it writes, so on a branch
    that ships one feature but not the other we never report a write that didn't land. If the
    write transaction fails, we roll back AND reset the reported counts to zero."""
    Spec = dbmod.SellerSpec
    disk_cols = ("disk_enabled", "disk_provider", "disk_alloc_gb",
                 "disk_used_gb", "disk_est_daily_usd", "disk_reported_at")
    idle_cols = ("idle_fallback", "idle_algo", "idle_hashrate",
                 "idle_est_daily_usd", "idle_reported_at")
    disk_ok = _has_cols(Spec, *disk_cols)
    idle_ok = _has_cols(Spec, *idle_cols)
    out = {"disk": 0, "idle": 0, "disk_supported": disk_ok, "idle_supported": idle_ok}
    if not (disk_ok or idle_ok):
        return out
    s = dbmod.SessionLocal()
    try:
        for i, sp in enumerate(_demo_specs(dbmod, s)):
            if disk_ok and i % 2 == 0:          # every other node rents spare disk
                alloc = _DISK_ALLOC[i % len(_DISK_ALLOC)]
                sp.disk_enabled = True
                sp.disk_provider = _DISK_PROVIDERS[i % len(_DISK_PROVIDERS)]
                sp.disk_alloc_gb = alloc
                sp.disk_used_gb = round(alloc * 0.4, 1)
                sp.disk_est_daily_usd = round(alloc / 1000.0 * 1.5 / 30.0, 4)
                sp.disk_reported_at = dbmod._utcnow()
                out["disk"] += 1
            if idle_ok and i % 3 == 0:          # some also idle-mine when unrented
                sp.idle_fallback = True
                sp.idle_algo = "daggerhashimoto"
                sp.idle_hashrate = round(60.0 + i * 7.5, 1)
                sp.idle_est_daily_usd = round(0.35 + i * 0.12, 4)
                sp.idle_reported_at = dbmod._utcnow()
                out["idle"] += 1
            s.add(sp)
        s.commit()
    except Exception as e:                      # noqa: BLE001 — best-effort enrichment
        s.rollback()
        out["disk"] = out["idle"] = 0           # nothing persisted — don't report phantom writes
        print(f"  ! disk/idle enrichment skipped: {e}", file=sys.stderr)
    finally:
        s.close()
    return out


def seed_cluster(dbmod):
    """A formed distributed cluster (kind=distributed) across demo nodes, with every rank's
    rendezvous address registered so /cluster + /jobs/manifest render a ready cluster.

    Returns {"status": ..., "id": job_id_or_None}, distinguishing:
      unsupported  — the distributed-cluster feature isn't in this build
      unavailable  — the feature exists but there isn't enough demo supply to form a cluster
      failed       — a write raised (details on stderr)
      created      — a cluster was formed (id set)"""
    if not _has_fns(dbmod, "create_distributed_job", "add_job_segment", "register_peer",
                    "set_rendezvous"):
        return {"status": "unsupported", "id": None}
    s = dbmod.SessionLocal()
    try:
        buyer = _first_demo_buyer(dbmod, s)
        specs = _demo_specs(dbmod, s)[:3]
        if not buyer or len(specs) < 2:
            return {"status": "unavailable", "id": None}
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
        return {"status": "created", "id": job.id}
    except Exception as e:                      # noqa: BLE001
        s.rollback()
        print(f"  ! cluster enrichment skipped: {e}", file=sys.stderr)
        return {"status": "failed", "id": None}
    finally:
        s.close()


def seed_vms(dbmod):
    """A couple of rentable VMs with STABLE addresses: one running, one that 'migrated' nodes
    (its address unchanged) — so the VM UI + the dynamic-DNS story have live content.

    Returns {"status": ..., "ids": [...]}, using the same status vocabulary as seed_cluster."""
    if not _has_fns(dbmod, "create_vm_route", "register_vm_tunnel", "vm_event"):
        return {"status": "unsupported", "ids": []}
    ids = []
    s = dbmod.SessionLocal()
    try:
        buyer = _first_demo_buyer(dbmod, s)
        specs = _demo_specs(dbmod, s)
        booking = (s.query(dbmod.Booking).filter(dbmod.Booking.buyer_id == buyer.id).first()
                   if buyer else None)
        if not buyer or not booking or len(specs) < 2:
            return {"status": "unavailable", "ids": []}
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
        return {"status": "created", "ids": ids}
    except Exception as e:                      # noqa: BLE001
        s.rollback()
        print(f"  ! VM enrichment skipped: {e}", file=sys.stderr)
        return {"status": "failed", "ids": ids}
    finally:
        s.close()


def main(argv):
    keep = "--keep" in argv
    demo._bootstrap_env()
    from fastapi.testclient import TestClient
    import db as dbmod
    import main as app_main

    if keep:
        try:
            dbmod.init_db()                     # ensure the schema exists (idempotent)
        except Exception:                       # noqa: BLE001
            pass
        if _demo_data_present(dbmod):
            print("  (--keep) existing demo data found — skipping base seed; enriching in place.")
            summary = _summary_from_db(dbmod)
        else:
            client = TestClient(app_main.app)
            summary = demo.seed(client, dbmod)  # empty DB: seed once, then enrich
    else:
        demo.wipe(dbmod)
        client = TestClient(app_main.app)
        summary = demo.seed(client, dbmod)      # tested base (marketplace + jobs + settlement)

    disk = enrich_disk_idle(dbmod)
    cluster = seed_cluster(dbmod)
    vms = seed_vms(dbmod)
    demo._stamp_demo(dbmod)                      # keep any newly-touched demo rows labelled

    def _skip_note(status, unit):
        return {
            "unsupported": f"skipped — {unit} not in this build",
            "unavailable": f"skipped — not enough demo supply to form {unit}",
            "failed": f"attempted but failed (see stderr) — {unit}",
        }.get(status, f"skipped — {unit}")

    disk_line = (f"{disk['disk']} node(s) contributing  ->  /seller disk UI, /disk/providers"
                 if disk["disk_supported"] else "skipped — spare-disk columns not in this build")
    idle_line = (f"{disk['idle']} node(s)                ->  idle earnings UI"
                 if disk["idle_supported"] else "skipped — idle-mining columns not in this build")

    if cluster["status"] == "created":
        cluster_line = (f"job #{cluster['id']}                     ->  "
                        f"/cluster, /jobs/manifest/{cluster['id']}")
    else:
        cluster_line = _skip_note(cluster["status"], "distributed cluster")

    if vms["status"] == "created":
        n = len(vms["ids"])
        shape = "1 running, 1 migrated" if n >= 2 else "partial"
        vm_line = f"{n} ({shape})  ->  /console Compute tab (stable address)"
    else:
        vm_line = _skip_note(vms["status"], "rentable VMs")

    demo._print_info(summary)
    print("  UI/UX enrichment (all labelled demo, no fabricated earnings):")
    print(f"    spare-disk rental ... {disk_line}")
    print(f"    idle mining ......... {idle_line}")
    print(f"    distributed cluster . {cluster_line}")
    print(f"    rentable VMs ........ {vm_line}")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
