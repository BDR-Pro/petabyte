# CLI

`petabyte` is the command line. It serves **buyers** (rent + run compute), **everyone** (manage AI
models), and account basics. **Selling** is done by the [agent](sellers.md) daemon, not this CLI.

Run it as `python cli/petabyte.py …` (dev) or, once installed, `petabyte …`. Model commands are also
available standalone as `python -m modelhub …`.

## Setup

```bash
pip install httpx                                   # the only dependency for the compute commands
export PETABYTE_API_URL=http://localhost:8000       # or pass --api ; saved after first login
```

Config + saved token live in `~/.petabyte/cli.json`. Set `NO_COLOR=1` for plain output.

## Account & compute (buyer)

| Command | What it does |
|---|---|
| `petabyte register -u <user> -p <pass>` | create an account |
| `petabyte login -u <user> -p <pass>` | sign in (stores a token) |
| `petabyte wallet` | show balance **and** earnings |
| `petabyte deposit <amount>` | add funds (test credit in the sandbox) |
| `petabyte specs` | list bookable GPUs (price, units, trust, provider) |
| `petabyte run <file.ipynb\|.py> [--gpu H100] [--hours 1] [--vpn]` | book the cheapest matching GPU, escrow, run, print the result |
| `petabyte vpn <booking_id> [-o file.conf]` | download the WireGuard config for a VPN booking |

## Seller (read node & payout state, feed cache-locality)

The heavy lifting is the [agent](sellers.md) daemon, but these read/curate your node from anywhere
you're signed in:

| Command | What it does |
|---|---|
| `petabyte earnings` | balance, withdrawable earnings, what's still clearing, recent payouts |
| `petabyte node status <spec_id>` | online/attested, price + suggestion, utilization, jobs, reputation, earnings, cached models, blockers |
| `petabyte node sync-models <spec_id>` | scan this machine's `~/.petabyte` cache and report it to the marketplace, so the scheduler prefers your node for jobs needing a model you already hold |

`node sync-models` runs on the machine that has the cache (usually the node itself). The agent does
this automatically over time; run it by hand to push updates immediately.

## Models (anyone — works locally, no account needed)

| Command | What it does |
|---|---|
| `petabyte model search "<query>"` | discover models (table: params, license, pulls) |
| `petabyte model info <id>` | manifest + hardware fit + trust |
| `petabyte model pull <id>` | download + verify + cache (progress, speed, ETA, resume) |
| `petabyte model list` | installed models |
| `petabyte model inspect <id>` | files + which blobs are shared |
| `petabyte model remove <id>` | uninstall (blobs kept for dedup) |
| `petabyte model cache status` / `prune` | cache usage / reclaim unreferenced blobs |
| `petabyte pull <id>` | alias for `model pull` |
| `petabyte run <id>` | ensure a model is present, then hand it to a runtime |
| `petabyte auth huggingface` | save a token for gated/private models (never printed) |

`run` is smart: given a **file** it runs a compute job on a rented GPU; given a **model id**
(`org/model`) it ensures the model is installed and hands the local path to a runtime.

## Examples

```bash
# rent + run a notebook on the cheapest 4090
petabyte run train.ipynb --gpu "RTX 4090" --hours 2

# pull a model, see if it fits this machine, then run it
petabyte model info Qwen/Qwen3-8B
petabyte model pull Qwen/Qwen3-8B
petabyte run Qwen/Qwen3-8B

# a gated model
petabyte auth huggingface           # paste your HF token (hidden)
petabyte model pull meta-llama/Llama-3.1-8B-Instruct
```

Full model behaviour (formats, quantization, resume, cache layout, security) is in [Models](models.md).
