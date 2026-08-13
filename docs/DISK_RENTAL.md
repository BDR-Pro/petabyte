# DISK_RENTAL.md — rent a node's spare disk for extra money (web3 / BitTorrent)

A GPU node usually has a lot of spare disk. This lets a seller rent that disk to an existing
**decentralized storage network** (Storj, BitTorrent File System / BTFS, or Sia) for extra money.

**It is NOT an idle/fallback mode.** Disk rental is an **explicit** contribution the seller turns
on with real arguments — a **provider** *and* a **GB cap**, both required (neither is defaulted, and
the API refuses to enable without them). It runs **independently** of GPU rentals (disk isn't the
GPU), so it earns **whether or not a job is running** — it is never gated on the node being idle.

## The model — one account, one node name per machine

Petabyte runs **one account per storage network** and points every node at **Petabyte's platform
wallet**. Each node contributes under a **unique node name — `pbdisk-<spec_id>`** — so a settled
payout from the network maps **1:1 back to one seller** and lands in their **unified Petabyte
balance**. There is **no per-seller storage wallet** and no separate cash-out. (This per-node
attribution is the same trick NiceHash's `pb-<spec_id>` worker id uses — but disk rental itself is
always-on when configured, not an idle fallback.)

```
seller node (spare disk)
   └─ storage container, named  pbdisk-<spec_id>,  wallet = PETABYTE platform wallet
        └─ contributes to Storj / BTFS / Sia
network pays Petabyte  ──(per node name)──▶  disk_reconcile  ──▶  seller balance (− take rate)
```

## Seller controls (opt-in, and reversible at any time)

| Action | API | Effect |
|---|---|---|
| **Enable** + pick provider + set GB cap | `POST /nodes/disk {enabled:true, provider, alloc_gb}` (both required) | node starts contributing up to the cap |
| **Limit** (change the cap) | same call with a new `alloc_gb` | cap re-applied; clamped to `MAX_DISK_ALLOC_GB` |
| **Pause / deactivate** | `POST /nodes/disk {enabled:false}` | node stops earning; **data kept** (re-enable later) |
| **Delete / cancel** | `DELETE /nodes/{spec_id}/disk` | config cleared; agent **removes the container and wipes** the data dir |
| **Status** | `GET /nodes/{spec_id}/disk` | config, usage, node name, credited-to-date |
| **Providers** | `GET /disk/providers` | adapters + `est_usd_per_tb_month` + take rate |

Off by default on both sides: the **machine operator** must set `DISK_RENTAL_ENABLED=true` on the agent
*and* the **seller** must enable the node via the API. Either one off ⇒ nothing runs.

## How it runs on the node

The agent receives the disk config on each **heartbeat** and reconciles the container to it
(`lumaris_agent/task_fetcher._apply_disk_cfg`):

- **enabled + provider + cap** → `start_disk_node` launches `storjlabs/storagenode` / `btfs/node` /
  `hostd`, named `petabyte-disk-pbdisk-<id>`, with the seller's GB cap wired into the provider's
  max-storage flag and the platform wallet + node name set for attribution
  (`lumaris_agent/disk_node.build_disk_cmd`, a pure/tested function).
- **disabled** → `stop_disk_node` (pause, keep data).
- **deleted** (config cleared) → `remove_disk_node` (stop + wipe the data dir).

The node reports usage + an estimated daily trickle via `POST /nodes/disk_report` for the seller's
visibility. It runs concurrently with GPU jobs.

## Money flow (the ledger)

`disk_reconcile` (a timer job) pulls **settled** per-node earnings from the provider and calls
`db.reconcile_disk_earnings`, which is idempotent per `(node_id, period)` and posts a balanced
entry per settlement:

```
external:storage      DEBIT   gross
seller_earnings:<uid> CREDIT  gross × (1 − STORAGE_TAKE_RATE)     # the seller's cut
platform_revenue      CREDIT  gross × STORAGE_TAKE_RATE           # Petabyte's take
```

## Configuration

| Var | Scope | Default | Meaning |
|---|---|---|---|
| `DISK_RENTAL_ENABLED` | agent | `false` | operator allows disk rental on the machine |
| `DISK_PAYOUT_WALLET` | agent | – | Petabyte's platform storage wallet set on every node |
| `DISK_DATA_DIR` | agent | `/var/lib/petabyte/disk` | host dir for node data (per-node subdir) |
| `DISK_PROVIDER` | platform | `storj` | default adapter for reconciliation |
| `DISK_REFERENCE_USD_PER_TB_MONTH` | platform+agent | `1.5` | reference for the pre-commit estimate |
| `STORAGE_TAKE_RATE` | platform | `0.10` | platform commission on storage earnings |
| `MAX_DISK_ALLOC_GB` | platform | `100000` | hard ceiling on one node's pledge |
| `STORAGE_STUB` | platform | `false` | offline earnings stub for tests |
| `STORAGE_STUB_EARNINGS` | platform | – | test-only JSON `{node_id: usd}` |

## Honest status

- **Implemented + tested** (`lumaris_api/disk_rental_test.py`, in CI): opt-in/limit/disable/delete,
  the GB-cap clamp, provider validation, the **unique per-node attribution name**, the heartbeat
  config delivery, usage reporting, ownership isolation, and the **reconcile** — seller/platform
  split, attributed by node name, idempotent per `(node, period)`. Plus the agent's pure launch
  logic (`disk_node.build_disk_cmd`): the docker command, the GB cap wired into the provider flag,
  and platform-wallet (not per-seller) attribution.
- **The operator step (adapter seam)** — same honesty as NiceHash needing org credentials and the
  Circle payout adapter being flag-gated: bringing a **real** Storj/BTFS/Sia node fully online needs
  **provider onboarding** — a funded platform wallet and the provider's identity/auth tokens — and
  the real per-node **earnings pull** in `storage_providers.get_node_earnings`. Until that's wired,
  it refuses to invent earnings (tests use `STORAGE_STUB=true`); it never fabricates a payout.
- **Host protection:** the storage container runs like any other node workload (see the agent's
  isolation flags). Only the seller-approved `alloc_gb` of disk is ever pledged, and delete wipes
  the data dir.

See also: idle mining (`tools/idle_reconcile.py`, the GPU analogue) and `docs/PRICING_MODEL.md`.
