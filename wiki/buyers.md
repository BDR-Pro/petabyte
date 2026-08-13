# For buyers

Everything you do as someone renting compute. All of it lives in the **Console** (`/console`) and/or
the [CLI](cli.md).

## Wallet & escrow

- **Add funds** in Console → *Wallet & billing*. In the sandbox this is test credit; in live mode
  it's a card at checkout.
- When you book compute, the cost is **escrowed** (reserved), not spent. It's released to the seller
  as the work is delivered. Unused hours are **refunded** — if a node drops, you get your money back.
- **Spend** shows your current burn rate and a projection so a runaway job can't surprise you.

## Running a job

- **Console → Compute → Run on cheapest GPU.** Paste a notebook or Python and run it on the cheapest
  matching GPU. The result streams back into the page.
- Or pick a specific GPU from the marketplace / *Available GPUs* table (sorted by real
  price-vs-cloud savings and trust level).
- CLI: `petabyte run notebook.ipynb --gpu H100 --hours 1` books, escrows, dispatches, and prints the
  result.

## VMs that survive failover

Launched VMs get a **stable address** that survives a node dropping — Petabyte fails the workload
over to another node and keeps the same address. See your VMs under **Console → Compute → Your VMs**.
For a private network, book with a **WireGuard VPN** (`--vpn` on the CLI) and you get a client
config to `wg-quick up`.

## Distributed clusters

For multi-GPU training/inference across many machines: **Console → Clusters** (or `/cluster`).
Petabyte gang-schedules the nodes and wires them together over a private VPN so `torchrun` / MPI /
Ray "just work." Nodes are matched together and given a rendezvous endpoint.

## Models

Discover and install open models (Llama, Qwen, Mistral, …) from **Console → Storage/Models** or the
public **`/models`** catalog, or with `petabyte model pull <id>`. A job can then request a model by
id and the scheduler prefers a node that already has it cached. See [Models](models.md).

## Persistent storage

VMs are ephemeral. To keep datasets, checkpoints and weights **between runs**, create a
[persistent volume](storage.md) — snapshots are incremental (only changed content is uploaded) so
you pay for unique bytes, not a full-disk mirror.

## Teams

Share one wallet across a lab or company with a hard **budget cap**, add members with roles
(admin / billing / member), and get an immutable audit log. See [Teams & security](teams-and-security.md).

## Confidential & region-verified compute

Some listings are **confidential** (run inside a hardware enclave — TEE) or **region-verified**
(the node's country is GeoIP-confirmed against its claim), for workloads with data-residency or
privacy requirements. These are labelled in the marketplace.

## Buyer checklist

1. Add funds → 2. Pick "cheapest match" or a specific verified GPU → 3. Run → 4. Get the result;
unused time is refunded automatically. Receipts and per-job **verifiable receipts** are under
*Wallet & billing* and the public trust page.
