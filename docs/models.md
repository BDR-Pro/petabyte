# models.md — discover, download and manage open AI models

Petabyte gives open models the convenience of Hugging Face / `ollama pull` / Docker pulls, with a
**provider-independent** local layer. One identifier, one command:

```bash
petabyte model pull meta-llama/Llama-3.1-8B-Instruct
```

You never touch a storage URL, pick individual `.safetensors` shards, manage checksums, or babysit a
download. Petabyte resolves the identifier, selects the compatible files, verifies hashes, resumes
broken transfers, and caches everything content-addressed so nothing is stored twice.

The exact same engine (`lumaris_api/modelhub/`) powers the CLI, the web **Models** section, and the
marketplace cache-locality signal. Search + info are also public in the web UI at `/models`.

---

## Model identity

```
[source:]publisher/model[:tag][@revision]
[source:]alias[:tag]                 # short alias resolved by the Petabyte registry
https://mirror.example.com/model.json  # a direct manifest URL
```

Examples:

```bash
petabyte model pull Qwen/Qwen3-8B
petabyte model pull mistralai/Mistral-7B-Instruct-v0.3@e0bc86c
petabyte model pull hf:meta-llama/Llama-3.1-8B-Instruct
petabyte model pull llama3.1:8b        # alias -> meta-llama/Llama-3.1-8B-Instruct
```

`source` selects the provider (`hf` is the default). Identifiers are strictly charset-validated so an
id can never turn into a path-traversal.

## Sources (providers)

Petabyte codes against a small provider abstraction — `search / resolve / manifest / download URLs` —
so the rest of the platform never cares where a model is hosted:

| Source | Adapter | Notes |
|---|---|---|
| `hf` (default) | Hugging Face | HF HTTP API; LFS `oid`s give real sha256 for verification; gated-model aware |
| `http`/`https` | direct URL | a JSON manifest at a mirror / CI fixture (unverified source) |
| `pt` | Petabyte registry | curated short aliases → upstream open models (offline static table + optional `PETABYTE_REGISTRY_URL`) |

Hugging Face is a first-class source, not a wrapper around `huggingface-cli`: Petabyte owns the
higher-level UX (file selection, normalized manifests, compatibility, verification).

## CLI

```bash
petabyte model search "code 7b"          # discover (table: model, params, license, pulls)
petabyte model info Qwen/Qwen3-8B        # manifest + hardware fit + trust
petabyte model pull Qwen/Qwen3-8B        # download + verify + cache (progress, speed, ETA, resume)
petabyte model list                      # installed models
petabyte model inspect Qwen/Qwen3-8B     # files + which blobs are shared
petabyte model remove Qwen/Qwen3-8B      # remove (blobs kept for dedup; reclaim with cache prune)
petabyte model cache status              # total storage, shared + reclaimable blobs
petabyte model cache prune               # delete unreferenced blobs (never a referenced one)

petabyte pull Qwen/Qwen3-8B              # alias for `model pull`
petabyte run  Qwen/Qwen3-8B             # ensure present, then hand the local path to a runtime
```

Also runnable as `python -m modelhub ...`. Output is colored, tabular, and honest about
verification and hardware fit. Set `NO_COLOR=1` for plain output.

### Selecting a variant

```bash
petabyte model pull <id> --format safetensors        # or gguf / onnx
petabyte model pull <id> --quantization Q4_K_M       # for gguf
petabyte model pull <id> --revision <branch|sha>
petabyte model pull <id> --force                     # ignore a "won't fit" hardware verdict
```

Petabyte prefers `safetensors` and never silently mixes weight formats. If you ask for a format the
model doesn't publish, it tells you which formats are available.

## Resumable, reliable downloads

Downloading is treated as infrastructure, not an HTTP GET:

- HTTP **range** requests + resume from a `.partial` file (re-hashing what's already on disk) — a
  connection lost at 98 % continues, it does not restart;
- retry with **exponential backoff** on connection loss, HTTP **429** (honouring `Retry-After`) and
  **5xx**;
- streaming **sha256** verification and corrupted-file detection (a wrong-size cached blob is healed
  on the next pull);
- **atomic finalization** — the file is renamed into place only after its bytes verify;
- disk-space **preflight** and `ENOSPC` handling;
- safe **cancellation** (leaves a `.partial` to resume);
- a per-model **lock** so two concurrent pulls of the same model can't corrupt the cache.

## Content-addressed cache

```
~/.petabyte/                     # or $PETABYTE_HOME
  blobs/sha256/<hash>            # deduplicated content store — one copy per distinct blob
  manifests/<pub>/<model>/<rev>.json
  refs/<pub>/<model>/<tag>       # a tag -> revision pointer
  models/<pub>/<model>/<rev>/    # the materialized tree a runtime consumes (links into blobs)
```

If two models or two revisions share a blob (same sha256) it is stored **once** and every model dir
links to it. `cache prune` reclaims only blobs nothing references; a blob in use is never deleted.

## Manifests

Every provider resolves a model to one normalized manifest (`schema_version`, `id`, `revision`,
`architecture`, `parameters`, `context_length`, `format(s)`, per-file `{path,size,sha256}`,
`total_size`, `license`, `requirements {vram_gb, ram_gb, disk_gb}`, `trust`, `gated`). It is written
to `manifests/…` on install and is the single contract the CLI, web UI, and runtimes read.

## Hardware-aware

`petabyte model info` and the web model page detect CPU / RAM / GPU / VRAM / accelerator
(CUDA/ROCm) / free disk and judge the model against them:

- **Good** — runs comfortably.
- **Tight** — fits, or CPU-only (slower).
- **Insufficient** — won't fit; for a VRAM shortfall it suggests lighter quantizations that would.

Nothing is blocked for an expert — `--force` downloads anyway.

## Hugging Face auth (gated / private models)

```bash
petabyte auth huggingface           # prompts for a token; stored 0600 in ~/.petabyte/auth.json
# or: export HF_TOKEN=hf_xxx        # (HUGGING_FACE_HUB_TOKEN / HUGGINGFACE_TOKEN also accepted)
```

Tokens are **never printed or logged**. A gated model without a token returns a clear message with
the license URL to accept, then a retry hint.

## Security

- Remote artifacts are treated as untrusted: manifest file paths are charset-checked and can **never
  escape** their model directory (no `..`, absolute paths, drive letters, backslashes, or symlink
  games); blob keys are content-addressed.
- Hashes are verified when the source publishes them (HF LFS oids). The manifest's `trust` field
  distinguishes a **verified source** and **hash-verified weights** from unverified ones, and the UI
  shows it.
- Petabyte **never executes downloaded repository code**. `trust_remote_code` is off by default; a
  model that needs remote code requires a deliberate, separate opt-in.
- Tokens and private-model credentials are never emitted to logs.

## Web UI

- `/models` — searchable catalog with filters (license, max params, "fits my machine"), per-model
  compatibility badge and installed state.
- `/models/<publisher>/<model>` — model page: compatibility vs this machine, hardware requirements,
  files (with per-file verification), source & trust, and a one-click **Download** with live
  progress (`POST /api/models/pull` → poll `/api/models/downloads/{job_id}`).
- `/models/installed` — installed models with sizes and removal.

Server-side pull is **opt-in** (`MODEL_PULL_ENABLED=true`) because it writes tens of GB to the host —
appropriate for a self-hosted or inference node pre-warming models. The CLI always works locally.

## API

```
GET    /api/models/search?q=&license=&architecture=&max_params=&source=
GET    /api/models/featured
GET    /api/models/machine
GET    /api/models/installed
GET    /api/models/availability?id=<model>      # cache-locality: nodes that already hold it
GET    /api/models/{id}                          # normalized manifest + compatibility + installed
POST   /api/models/pull            {id, format?, quantization?, revision?, force?}  (auth; opt-in)
GET    /api/models/downloads/{job_id}            # live download progress
DELETE /api/models/{id}                          # remove from this node (auth)
```

## Marketplace cache-locality

A seller node reports the model ids it holds locally:

```
POST /nodes/models   {spec_id, models:[...]}     # agent, X-API-KEY
GET  /nodes/{spec_id}/models                      # owner
```

The scheduler uses this as a tiebreaker (`db.rank_specs_for_model`): when two nodes are otherwise
comparable, the one that already has the model wins — so a 20–100 GB weight file isn't re-downloaded.
`GET /api/models/availability?id=` reports how many online nodes already hold a model.

A seller can report their node's cache from the CLI:

```
petabyte node sync-models <spec_id>   # scan ~/.petabyte and POST the ids to /nodes/models
petabyte node status <spec_id>        # shows cached-model count among node health
```

`POST /nodes/models` accepts either the agent's API key **or** the node owner's bearer token, so
both the daemon and the CLI can report. The endpoint, DB field (`specs.cached_models`), ranking
helper (`db.rank_specs_for_model`) and availability API are shipped and tested. Wiring the agent
daemon to call it automatically on each heartbeat is a one-line addition to its loop.

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `PETABYTE_HOME` | `~/.petabyte` | cache root (blobs/manifests/refs/models) |
| `HF_ENDPOINT` | `https://huggingface.co` | Hugging Face endpoint (override for a mirror/tests) |
| `HF_TOKEN` | — | token for gated/private models (never logged) |
| `PETABYTE_REGISTRY_URL` | — | optional registry for extra aliases |
| `MODEL_PULL_ENABLED` | `false` | allow server-side pulls on this node |
| `MODEL_MAX_PULL_GB` | `200` | per-pull size ceiling (server-side) |
| `VOLUME_MAX_BLOB_MB` | `1024` | (persistent volumes) through-API blob cap |
| `NO_COLOR` | — | disable CLI color |

## Troubleshooting

- **"gated model"** — run `petabyte auth huggingface` after accepting the license on the model page.
- **"needs ~N GB VRAM"** — pull a smaller quantization (`--quantization Q4_K_M`) or `--force` to run
  on CPU/offload (slower).
- **stalled/failed download** — just re-run `petabyte model pull`; it resumes from the `.partial`.
- **"format not available"** — the message lists the formats the model actually publishes.
- **"server-side pull is disabled"** — that node has `MODEL_PULL_ENABLED=false`; install locally with
  the CLI instead.

## Tests

`lumaris_api/modelhub_test.py` (hermetic, in CI) runs the whole loop against a real local HTTP server
with HTTP range + fault injection: id parsing & path-sanitization, manifest estimates, cache dedup +
prune, resumable download through a mid-stream connection drop / 429 / 500, checksum + corruption
healing, gated auth, provider file-selection, the full search→resolve→pull→verify→install cycle, and
the CLI output. Cache-locality endpoints are covered by `smoke_test.py`.
