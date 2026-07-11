# vm-rental.md — reachable VMs, stable URLs, failover

**Status: routing + failover LOGIC is BUILT and tested in software; the physical
gateway/tunnel/S3 restore still need real machines.** `/launch` now creates a
`VMRoute` and returns a stable address (`ssh vm-<id>@petabyte.market`); nodes
register their tunnel; the reaper migrates live VMs to a new node on death with
the address unchanged. What's left is the actual frp gateway, the node-side frpc,
and real S3 snapshot/restore — all of which need real hosts (see RLtest.md §24-25).

---

## Why not "just SSH to the seller's IP"

- Most sellers are behind **NAT** (home/office routers) — their IP isn't
  reachable at all.
- Exposing a seller's real IP is a security/privacy hole (attack surface, DDoS,
  deanonymization).

So we need a **gateway** with a **stable address** and a **reverse tunnel**.

## Connect model (form matters)

- SSH: `ssh vm-<id>@petabyte.market` — the **username routes** to the VM (SSH has
  no query string). Alt: per-VM host `vm-<id>.petabyte.market`.
- Web apps (Jupyter/ComfyUI/SD): `https://<vmid>.petabyte.market`.
- `region` is a **placement hint at creation**, not part of the connect string —
  once the VM exists it's pinned to a `vm_id`.

The address is **permanent**; the platform routes it to whatever node currently
hosts that VM.

## Architecture

```
buyer ──ssh vm-42@petabyte.market──▶ GATEWAY (public)
                                      │  looks up vm_id=42 in routing table
                                      │  proxies down the node's outbound tunnel
                                      ▼
                            frps  ◀──frpc dials out──  SELLER NODE (behind NAT)
                                                        └─ container (SSH:22, app port)
```

- **Gateway** (`gateway.petabyte.market`): `frps` + an SSH router (reads
  `vm-<id>` username → upstream) + an HTTP reverse proxy with dynamic upstreams.
- **Reverse tunnel:** node runs `frpc`, **dials out** to the gateway (works
  through NAT), exposes the container's SSH + app port. (WireGuard is the
  alternative; frp is simpler for v1 — see isolation-roadmap.)
- **Routing table** (durable — Postgres/Redis, NOT local memory): `VMRoute`
  = `vm_id, buyer_id, template, current_node_id, tunnel_port, status, ssh_key,
  snapshot_url, updated_at`. This is the "local persistent hashmap" idea, made
  durable so it survives restarts and works across multiple gateways.

## Failover (same URL, new node)

Your model: `Buyer1/VM1 = ip_A` → node A dies → `Buyer1/VM1 = ip_B`, **URL
unchanged**.

1. Heartbeat/reaper detects node A down (already exists).
2. Orchestrator picks a new eligible seller (node B).
3. Node B restores the latest **S3 snapshot** (via `/jobs/restore_url`) and starts
   the container.
4. Node B registers its tunnel; orchestrator **updates `VMRoute.current_node_id`**.
5. Buyer reconnects to the same address → lands on node B.

**Honest caveat:** this is **crash-consistent, not zero-loss.** State between
snapshots (RAM, un-synced writes) is gone; the session restarts from the last
checkpoint. True live migration (CRIU/live memory) is very hard and out of scope.
Tell users: "files safe to the last snapshot; the session reconnects."

## Checkpoint → S3

Agent loop: periodically snapshot the container volume (`docker commit` / volume
tar in Phase 1; VM snapshot in Phase 2) and push to S3 via the existing
`/jobs/backup_url` presign flow. Store the latest `snapshot_url` on the `VMRoute`
row. Governed by `S3_STUB` (see stub.md) — simulated until real S3 creds.

## Build order (thin slices, each testable)

1. **[BUILT] `VMRoute` table + routing endpoints** (`POST /vm/register_tunnel`,
   `GET /vm`, `GET /vm/{id}`, `POST /vm/{id}/stop`, `GET /vm/{id}/route`
   gateway-token-gated). Tested: two-node failover flips the row, address constant.
2. **[BUILT] `/launch` returns the stable URL** and creates the `VMRoute` row.
3. **[REAL MACHINE] Gateway**: frps + SSH-username router + HTTP reverse proxy.
4. **[REAL MACHINE] Agent**: start container -> launch `frpc` -> `POST
   /vm/register_tunnel`.
5. **[REAL MACHINE] Checkpoint -> S3** loop (governed by `S3_STUB`).
6. **[BUILT — logic] Failover orchestrator** wired to the reaper
   (`reap_and_failover`): detect dead node -> pick new eligible node -> reserve
   -> re-point `VMRoute.current_spec_id` -> node re-registers. End-to-end restore
   needs S3 + 2 real nodes.
7. **[PARTIAL] Lifecycle + metering**: `POST /vm/{id}/stop` built; `extend`,
   teardown, per-hour metering, auto-stop on funds exhaustion still to do.

## Prove the thinnest slice first

One node behind (simulated) NAT dials out to one gateway; buyer does
`ssh vm1@gateway` and lands in the container. **No S3, no failover yet.** Just
prove NAT-traversal + stable-address proxying works end to end. Then add S3
checkpoint. Then add failover. Each step: 2-3 cheap cloud VMs.

## What can be built in software now (no real machines)

Steps 1, 2, and the failover **logic** in step 6 — with tests that simulate a
two-node failover and assert the routing row flips while the connect string stays
constant. That proves the hashmap+failover design; only the physical frp/tunnel
proof needs real boxes.
