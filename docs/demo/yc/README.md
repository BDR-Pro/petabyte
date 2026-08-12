# Petabyte — YC / investor demos

Everything for demoing Petabyte live lives here. There are **two** demos; pick by the story you
want to tell. Both run the real product — real Stripe **TEST** mode, real nodes, real signed
results — and neither fakes anything in a way that would mislead.

| Demo | Story it tells | Nodes | Doc |
|---|---|---|---|
| **Single-node marketplace** | "A stranger's GPU, rented and paid, in the browser." The two-sided money loop. | 1 seller GPU + 1 buyer | [`browser-single-node.md`](browser-single-node.md) |
| **Distributed cluster** | "One job across two machines — real gang-scheduling + execution." The scale loop. | **2 GPU VMs** (2 seller accounts) + 1 buyer | [`distributed-two-gpu-vms.md`](distributed-two-gpu-vms.md) |

If you only run one thing on stage, run the **single-node** demo — it's the clearest, and the
payment story is what most people ask about. Add the **distributed** demo to answer "does this
actually scale past one box?" — the answer is now yes, and it's runnable in ~one command.

---

## Which one answers your question?

- *"Is there a real marketplace with real payments?"* → single-node. A seller brings a GPU
  online, a buyer rents it in the browser, pays with a Stripe TEST card, the workload runs on the
  real GPU, both sides see the money, and the seller payout is held 14 days. No `curl`, no internal
  endpoints touched by hand.
- *"Can one job span multiple machines?"* → distributed. One buyer launches a **2-node cluster**;
  the router gang-schedules two **distinct** machines, escrows both all-or-nothing, and each node's
  agent registers its rank, joins the master, executes, and reports a **signed** result. The
  cluster completes only when **every** rank does; one dead rank fails the whole run.

---

## What is real today (be precise on stage)

| Capability | State | Proven by |
|---|---|---|
| Marketplace, quote, escrow, capture, seller payout (held 14d) | **real** | `browser-e2e` (CI), `make e2e-real` |
| Real GPU execution of a single job | **real** | `smoke-gpu` on self-hosted GPU (`scripts/smoke_gpu.py`) |
| Distributed **control plane** — gang-schedule N distinct nodes, escrow all-or-nothing, rendezvous, hostfile/cluster export, gang-failure | **real** | `lumaris_api/distributed_test.py` (CI) |
| Distributed **execution** — each rank registers, resolves master, runs torchrun / built-in all-reduce, reports a signed result; cluster completes on all-ranks-done | **real** | `lumaris_agent/distributed_run_test.py` (real N-process all-reduce, CI) + the exec slice in `distributed_test.py` |
| Built-in **cluster self-test** (cross-process all-reduce, no GPU/image) | **real** | `distributed_run_test.py` — 4 real processes converge on the correct sum |
| Real **NCCL/GPU** collective over the WireGuard mesh | **works, needs setup** | matching CUDA image + `--vpn` + 2 GPU VMs; not run in CI (no multi-GPU CI) |
| Stripe **live money** | **off by design** | fails closed without `PAYMENTS_LIVE_ENABLED` + `sk_live_` |

**Honesty rule for the room:** the built-in all-reduce self-test runs on **CPU over TCP** — it
proves the cluster *wiring* (the two machines really talk and reduce correctly). A real training
job uses **NCCL on the GPUs over the mesh**; that's the same control plane, just a heavier
execution. Say which one you're showing.

---

## Drivers & scripts

| Script | Side | What it does |
|---|---|---|
| `scripts/e2e/seller_setup.sh` | seller VM | mint a node key → run the installer (attest + register + start agent) → verify GPU/Docker/agent |
| `scripts/e2e/buyer_probe.py` | buyer | single-node: login → quote → authorize → confirm → reserve → dispatch → receipt |
| `scripts/e2e/cluster_demo.py` | buyer | **distributed**: login → availability → `POST /distributed` → poll the manifest until every rank finishes |
| `scripts/smoke_gpu.py` | GPU host | bounded PyTorch matmul in the agent's container runtime + measured GPU utilisation |

## CI proofs (green = the claim holds)

- `browser-e2e` — the full buyer+seller browser journey, asserting the on-screen "charged" is a
  real server-side capture.
- `distributed compute` (`distributed_test.py`) — gang-schedule, escrow, rendezvous, export,
  gang-failure, **and** completion via real signed `/jobs/result`.
- `distributed EXECUTION` (`distributed_run_test.py`) — a **real multi-process all-reduce** where
  every rank converges on the correct answer, plus gang-failure with no false success.
- `smoke-gpu` (opt-in, self-hosted GPU) — genuine GPU work; never a fake PASS.

## Related reading (left in place, linked here)

- Product walkthrough: [`../../PRODUCT_DEMO.md`](../../PRODUCT_DEMO.md)
- Bring-your-own-scheduler (Slurm/MPI/Ray/K8s) + the execution loop: [`../../DISTRIBUTED_PROVIDER.md`](../../DISTRIBUTED_PROVIDER.md)
- Investor technical brief: [`../../INVESTOR_TECHNICAL_BRIEF.md`](../../INVESTOR_TECHNICAL_BRIEF.md)
- Observability demo: [`../../INVESTOR_OBSERVABILITY_DEMO.md`](../../INVESTOR_OBSERVABILITY_DEMO.md)
- Real GPU + real-Stripe E2E runbook: [`../../E2E_RUNBOOK.md`](../../E2E_RUNBOOK.md)
