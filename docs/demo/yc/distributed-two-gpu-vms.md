# Distributed demo — one buyer, two GPU VMs, one job across both

This is the **scale** demo: a single buyer launches **one job that runs across two separate
machines**, wired into one cluster. It shows the whole distributed loop — gang-scheduling,
all-or-nothing escrow, rendezvous, per-rank execution, and gang completion — on real nodes.

> **Can I do this today?** Yes. The control plane (gang-schedule, escrow, rendezvous, export,
> gang-failure) and the **execution loop** (each node registers its rank, resolves the master,
> executes, and reports a *signed* result) are implemented and tested. See the capability matrix
> in [`README.md`](README.md). Pick your execution mode below.

---

## Two ways to run the job

| Mode | What each node does | Needs | Use it for |
|---|---|---|---|
| **A. Cluster self-test** (recommended for stage) | the built-in cross-process **all-reduce** | nothing but the agent + a port between the VMs | proving the two machines really form a cluster and compute the correct global reduction — reliable, fast, no CUDA/NCCL to go wrong live |
| **B. Real training run** | your container under **`torchrun` + NCCL** | matching CUDA image on both VMs + the WireGuard mesh (`--vpn`) | the "real PyTorch DDP across two GPUs" flex — heavier, more moving parts |

Both use the **same** control plane and the same signed-result completion. Mode A is the honest,
low-risk way to *prove the cluster executes*; Mode B is the same thing with a real GPU workload on
top. **Say which one you're showing.**

---

## The two hard requirements (read these first)

1. **Two DISTINCT computers — each its own agent + API key + spec.** Anti-affinity for a
   distributed cluster is **per machine, not per account**: the router books one rank per *spec*
   (machine), so two ranks never land on the same registration. A single user can run **many
   computers** — mint one API key per computer at `/create_api_key` (label them, e.g. `pc0`,
   `pc1`) and run one agent per box. So the two VMs can be **one account with two keys** (a home
   lab) *or* two separate accounts — both work. Fewer than N distinct machines online →
   `INSUFFICIENT_DISTINCT_NODES`. *(Run one agent per physical box; two agents on one box are two
   specs and would be treated as two machines.)*
2. **The seller(s) must be payout-ready.** A node is only bookable when its owner
   `can_accept_paid_jobs` — i.e. has completed Stripe **TEST** Connect onboarding
   (`/seller/payouts`). One account → onboard **once**; two accounts → onboard each.

Plus the usual: the **buyer wallet must be funded** (every rank is escrowed up-front, all-or-
nothing — `world_size × price × hours`), and the API runs in real Stripe **TEST** mode (see
[`browser-single-node.md` §2a](browser-single-node.md)).

---

## Setup (~15 min, once)

### 1. Two seller VMs, each a live node

Recommended: **one account, two computers.** On **VM A** and **VM B**, run the installer helper as
the *same* seller — it mints a **separate node key per machine**, attests the hardware, registers a
spec, and starts the agent:

```bash
# on EACH VM, same account — the helper mints that machine's own API key + spec
PETABYTE_API_URL=https://petabyte.market SELLER_USER=labowner PRICE_PER_HOUR=1.5 \
  bash scripts/e2e/seller_setup.sh          # run on VM A, then again on VM B
```

Each machine ends up with its own `PETABYTE_API_KEY` + `PETABYTE_SPEC_ID` in
`/etc/petabyte/agent.env`. Complete Stripe **TEST** Connect onboarding **once** at
`/seller/payouts`; both machines then show **online · verified · payout-ready** in *Your GPUs*.
(Two separate accounts also work — onboard each — but one account + two keys is simpler.)

> No GPU on the VMs? Mode A (self-test) doesn't need one — it's CPU + a TCP port. You can run the
> whole distributed demo on two plain CPU VMs and it's still a genuine 2-node cluster forming and
> reducing. GPUs are only needed for Mode B.

### 2. Networking between the ranks

The ranks must reach each other on the rendezvous port (default `29500`):

- **Mode A / simplest:** ensure the two VMs can open a TCP connection to each other on `29500`
  (same VPC/subnet, or open the port between their addresses). Set `AGENT_VPN_ADDR` on each VM to
  the address its peer should dial if auto-detection picks the wrong interface.
- **Mode B (and the private-network story):** enable the WireGuard mesh so NCCL rides an encrypted
  10.x network — set `AGENT_VPN_ENABLED=true` on both agents and launch with `--vpn`. See
  [`../../DISTRIBUTED_PROVIDER.md`](../../DISTRIBUTED_PROVIDER.md) and `wireguard_startup.md`.

### 3. A funded buyer

Sign in as the buyer and top up the wallet (Stripe TEST card `4242 4242 4242 4242`) enough to
cover `world_size × price × hours` (e.g. 2 × $1.50 × 1h = **$3**).

---

## Run it — the browser (what you show on stage)

1. Buyer opens **petabyte.market → `/cluster`** ("Run one job across many GPUs").
2. **GPUs — one per machine:** `2`. **Max runtime:** `1`. **Backend:** NCCL (or Gloo for a CPU
   self-test).
3. Tick **"Cluster self-test first"** (Mode A) — the image/command fields grey out; the cluster
   runs the built-in all-reduce, no container needed. (For Mode B, leave it unticked and set the
   image + `torchrun …` command, and tick **Private network (VPN)**.)
4. Click **Form the cluster →**. The panel shows:
   - **escrow** (≈ $3 for two nodes, all-or-nothing),
   - **rank 0 (master)** and **rank 1** landing on **two different nodes**,
   - the **hostfile / torchrun / mpirun** commands (Petabyte = just another provider).
5. Each VM's agent claims its rank, registers its address, resolves the master, runs the job, and
   reports a **signed** result. The cluster flips to **complete** once **both** ranks finish.

Track it at `GET /jobs/manifest/{job_id}` (per-rank status + master address).

---

## Run it — one command (what you rehearse / fall back to)

`scripts/e2e/cluster_demo.py` drives the **buyer** side over the public API and watches the
cluster form and complete:

```bash
# Mode A — the reliable stage demo (built-in all-reduce, no GPU/image)
python3 scripts/e2e/cluster_demo.py \
  --api-url https://petabyte.market --buyer testUserBuyer \
  --world-size 2 --selftest

# Mode B — a real 2-node torchrun/NCCL training run over the VPN mesh
python3 scripts/e2e/cluster_demo.py --buyer testUserBuyer --world-size 2 --vpn \
  --image pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime \
  --command "torchrun train.py --epochs 3"
```

It prints: availability → the formed cluster (which rank on which node, escrow) → the export
commands → live manifest polling → a final **CLUSTER COMPLETE** (every rank ran and reported a
signed result) or **CLUSTER FAILED** (gang: one dead rank fails the run). It fakes nothing — the
VMs' agents do the execution; the script only reports what the server says.

---

## Failure modes to narrate (not bugs — the design)

| You see | Why | The point to make |
|---|---|---|
| `INSUFFICIENT_DISTINCT_NODES` | fewer than 2 distinct payout-ready **machines** online | anti-affinity is per-machine — two ranks never share a registration (one account can supply both) |
| `CLUSTER_BOOKING_FAILED`, nothing charged | wallet couldn't cover all N ranks | **all-or-nothing** escrow — a half-formed cluster is refused and refunded |
| cluster goes **failed** when you kill one agent | gang scheduling | one dead rank fails the whole run — no silent partial cluster |

These are worth *showing* on purpose: kill one agent mid-run and watch the manifest go `failed`.

---

## What this proves vs. what it doesn't

- **Proves:** a single buyer books **N distinct machines** as one cluster, pays for all of them
  all-or-nothing, the nodes **rendezvous and execute**, every rank reports a **signed** result,
  and completion/failure follow **gang** semantics — end to end, on real nodes.
- **Doesn't claim:** that the built-in self-test *is* NCCL. The self-test runs the all-reduce on
  **CPU over TCP** to validate the cluster wiring; a real training job (Mode B) runs **NCCL on the
  GPUs over the WireGuard mesh**. Same control plane, heavier execution.
- **Backed in CI:** the control plane + signed-result completion (`lumaris_api/distributed_test.py`)
  and a **real multi-process all-reduce** where every rank converges on the correct answer
  (`lumaris_agent/distributed_run_test.py`). Multi-GPU NCCL isn't run in CI (no multi-GPU runners);
  it's the same execution path exercised on real hardware.
