# Models

Petabyte gives open AI models the convenience of Hugging Face / `ollama pull`, with a
**provider-independent** local layer. One id, one command:

```bash
petabyte model pull meta-llama/Llama-3.1-8B-Instruct
```

…or the **Download** button in the web catalog at **`/models`**. You never touch a storage URL, pick
`.safetensors` shards, manage checksums, or babysit a download.

> This is a summary. The complete reference (every flag, cache layout, security details) is in
> [`docs/models.md`](../docs/models.md).

## Where models come from

Petabyte hosts **no** weights — it fetches them live from upstream:

- **Hugging Face** (default) — the real HF API; files verified against LFS hashes.
- **Direct HTTP** — a JSON manifest on any mirror.
- **Petabyte registry aliases** — short names like `llama3.1:8b` → an upstream model.

The catalog you see at `/models` is a small curated **featured** list so it isn't empty; searching
queries Hugging Face live, and you can pull anything on HF whether or not it's featured.

## Identity

```
[source:]publisher/model[:tag][@revision]      e.g.  Qwen/Qwen3-8B ,  hf:mistralai/Mistral-7B-Instruct-v0.3@e0bc86c
alias[:tag]                                     e.g.  llama3.1:8b
https://mirror/model.json                        # a direct manifest
```

## Add / remove

**Install / uninstall on your machine or a node:**

```bash
petabyte model pull  Qwen/Qwen3-8B      # add   (or the Download button on /models/<id>)
petabyte model remove Qwen/Qwen3-8B     # remove (or Remove on the model page)
petabyte model cache prune              # reclaim disk from unreferenced blobs
```

**Curate the catalog (what shows in `/models`):** edit `FEATURED` in
`lumaris_api/models_routes.py`, or add an alias in `lumaris_api/modelhub/providers/registry.py`.

## What makes it reliable

- **Resumable downloads** — HTTP range + `.partial` resume, retry/backoff on connection loss / 429 /
  5xx, streaming **sha256** verification, atomic finalize. A drop at 98 % continues; it never
  restarts from zero.
- **Content-addressed cache** at `~/.petabyte` — identical/unchanged blobs are stored once and shared
  across models; `prune` only reclaims what nothing references.
- **Hardware-aware** — `petabyte model info <id>` (and the model page) detect CPU/RAM/GPU/VRAM/disk
  and tell you *good / tight / insufficient*, suggesting lighter quantizations that would fit. Use
  `--force` to override.
- **Gated/private models** — `petabyte auth huggingface`; tokens are **never logged**. A gated model
  without a token returns a clear "accept the license, then retry" message.

## Security

Remote artifacts are treated as untrusted: manifest file paths can never escape the model directory,
weight hashes are verified when the source publishes them, the UI distinguishes verified vs
unverified sources/bytes, and **Petabyte never runs downloaded repository code** (`trust_remote_code`
off by default).

## Marketplace tie-in

A seller node reports which models it holds; the scheduler prefers a node that already has the model
so a job doesn't re-download tens of GB. See [For sellers](sellers.md) and `/api/models/availability`.
