# Glossary

Quick definitions for terms used across Petabyte.

- **Agent** — the small daemon a seller installs on a GPU machine. Attests the GPU, heartbeats, runs
  jobs, optionally earns from spare disk / idle mining. (`lumaris_agent/`)
- **Attestation** — a cryptographic proof that a GPU exists and is what it claims. Required before a
  GPU can be booked.
- **Blob** — one piece of content in the content-addressed store, keyed by its `sha256` and stored
  once. Used by both the model cache and persistent volumes.
- **Booking** — a buyer's reservation of a GPU for a number of hours; its cost is escrowed.
- **Buyer** — someone renting GPU compute.
- **Cluster** — several nodes gang-scheduled and networked (VPN) for distributed multi-GPU jobs.
- **Confidential compute (TEE)** — a workload run inside a hardware enclave so the host can't read it.
- **Console** — the signed-in web app at `/console` for buyers and sellers.
- **Delta** — the changed/new content a snapshot adds or a restore still needs (vs. a full copy).
- **Escrow** — funds reserved for a booking, released to the seller as work is delivered and
  refunded for unused/failed time.
- **Gateway** — routes traffic to rented VMs behind a stable address, with failover.
- **Manifest (model)** — the normalized description of a model: files, hashes, params, format,
  license, requirements, trust.
- **Model hub** — Petabyte's provider-independent discover/download/manage layer for open models.
- **Node** — a listed GPU machine (a `spec`), run by the agent.
- **Payout** — a seller withdrawal from their unified earnings balance.
- **Provider (model)** — a source adapter (Hugging Face, direct HTTP, Petabyte registry) behind the
  model hub.
- **Reputation / trust level** — how much a node has earned buyers' confidence: attested →
  benchmark-verified → job-proven → confidential/region-verified.
- **Scope (API key)** — what a key may do: `data` for the data API; `node`/`jobs` for compute.
- **Seller** — someone earning by renting out a GPU (and optionally disk / idle mining).
- **Snapshot** — a point-in-time manifest of files in a persistent volume.
- **Spec** — a listed GPU offering (the DB record behind a node): model, VRAM, price, units, trust.
- **TEST MODE** — the default sandbox: no real card charged, no real money moved; shown by a banner.
- **Volume** — a buyer's persistent storage that outlives a VM, built from incremental snapshots.
