# Workload Template Audit

**Run:** `e2e-20260805-213424` · **Commit:** `4f85ad9` · **UTC:** 2026-08-05
**Method:** static code review of the repository. **Live GPU / end-to-end
verification: NOT performed** — this environment has no route to the Droplets or
`https://petabyte.market`, no SSH key, and no GPU (see
`docs/BUYER_SELLER_GPU_E2E_REPORT.md` for the evidence). Therefore **no template
is marked `WORKING_AND_TESTED`** here: that label requires a real GPU run, which
is blocked. Each row's status is a code-review assessment plus an explicit
"GPU-verified?" column that is **NO (blocked)** for every entry.

> Honest-action note: I did **not** delete or hide any buyer-visible template.
> Removing production offerings requires evidence they are broken; I cannot
> obtain that evidence without live access, and deleting a working marketplace
> listing on a guess would be worse than leaving the audit open. Where the task
> requires "no buyer-visible template in a broken state," the correct next step
> is the live verification matrix at the end of this file — run once access
> exists — not a blind deletion.

---

## Two distinct things called "templates"

1. **Container templates** — `lumaris_api/templates_registry.py` `TEMPLATES` dict.
   A buyer picks one; the seller agent runs that container image on the GPU with
   a declared egress policy and (for serving templates) a port exposed through
   the tunnel. Exposed to buyers via `public_catalog()` (`templates_registry.py:107`).
2. **Built-in task types** — dispatched by `GET /jobs/next` (`main.py:1757`) and
   returned to the agent: `notebook`, `test`, `benchmark`, `render`, `transcode`,
   `stitch`, `template`, `vm`. These are the batch/interactive job kinds.

The result path `POST /jobs/result` (`main.py:1806`) is shared and is the
platform's validation backbone (see "Validation model" below).

---

## Validation model (already present — this is a real strength)

`/jobs/result` does **not** trust a bare `completed=true`:

- **Signed proof-of-work** — the result must carry a signature verified against
  the spec's attestation pubkey (`verify_signed_proof`, `main.py:1821`), binding
  the result to attested hardware. A forged/expired signature penalises
  reputation and records fraud (`main.py:1823-1830`).
- **Known-answer test workloads** (`test` task type) — the platform generates the
  workload server-side (size + seed, `main.py:1776`), computes the expected
  answer server-side, and compares the agent's `output_hash`
  (`record_test_result`, `main.py:1837`). The owner cannot fake a pass.
- **Escrow release on completion** — `release_booking` (`main.py:1861`) pays
  seller + platform only after a completed, signature-verified result.

This is the same shape the task's `pytorch-matmul-v1` asks for (server nonce/seed
→ execute on GPU → signed result → server-side validation → pay). `pytorch-matmul-v1`
should be built **on top of this existing machinery**, not from scratch (see the
gap analysis in the E2E report).

---

## Container templates (`TEMPLATES`)

> **Current registry (`templates_registry.py`):** the bookable catalog is **9**
> templates exposed via `public_catalog()` — `ollama`, `vllm`, `comfyui`, `blender`,
> `sd-webui`, `jupyter`, `minecraft`, `valheim`, `factorio`. The rows below for
> **`tensorrt-llm`, `ffmpeg`, `pytorch`** are **not** in `TEMPLATES` (they survive only
> as VRAM hints in `_MIN_VRAM`); `ffmpeg`/`pytorch` run as the `transcode` task type /
> bring-your-own image rather than as catalog templates, and `tensorrt-llm` is not
> currently offered. The full-audit rows are kept for their review notes.

| Template | Image | GPU | Egress | Kind | Code-review status | GPU-verified? |
|---|---|---|---|---|---|---|
| `ollama` | `ollama/ollama:latest` | yes | limited | LLM serve | FUNCTIONAL (interactive serve; no result validation — not a batch/validated job) | **NO (blocked)** |
| `vllm` | `vllm/vllm-openai:latest` | yes | limited | LLM serve | FUNCTIONAL (interactive serve) | **NO (blocked)** |
| `tensorrt-llm` | `nvcr.io/nvidia/tritonserver:24.05-trtllm-python-py3` | yes | limited | LLM serve | FUNCTIONAL (interactive serve; large image, `nvcr.io` pull) | **NO (blocked)** |
| `comfyui` | `yanwk/comfyui-boot:latest` | yes | limited | image gen | FUNCTIONAL (interactive serve) | **NO (blocked)** |
| `sd-webui` | `universonic/stable-diffusion-webui:latest` | yes | limited | image gen | FUNCTIONAL (interactive serve) | **NO (blocked)** |
| `ffmpeg` | `jrottenberg/ffmpeg:6.1-nvidia` | yes | none | transcode | FUNCTIONAL as batch via `/transcode`; egress `none` (good) | **NO (blocked)** |
| `blender` | `linuxserver/blender:latest` | yes | none | render | FUNCTIONAL as batch via `/render`; egress `none` (good) | **NO (blocked)** |
| `jupyter` | `quay.io/jupyter/pytorch-notebook:cuda12-latest` | yes | limited | notebook | FUNCTIONAL (interactive); **arbitrary code execution by design** — acceptable for a rented notebook, but NOT a validated batch job | **NO (blocked)** |
| `pytorch` | `pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime` | yes | limited | base | PARTIAL — base image, "bring your own script"; no packaged workload, no result validation | **NO (blocked)** |
| `minecraft` | `itzg/minecraft-server:latest` | no | limited | game | FUNCTIONAL (stateful serve, non-GPU) | n/a (no GPU) |
| `valheim` | `lloesche/valheim-server:latest` | no | limited | game | FUNCTIONAL (stateful serve, non-GPU) | n/a (no GPU) |
| `factorio` | `factoriotools/factorio:stable` | no | limited | game | FUNCTIONAL (stateful serve, non-GPU) | n/a (no GPU) |

**Egress model is sound** (`templates_registry.py:3-21`): default-closed, batch
templates are `none`, only serving templates are `limited`. No template is `open`.
This directly satisfies the task's "never permit arbitrary buyer shell/network
from a batch job" requirement — with the caveat that `jupyter`/`notebook` are
interactive code execution by design and must never be offered as a "validated
deterministic job."

## Built-in task types

| Task type | Source | Purpose | Result validation | Status |
|---|---|---|---|---|
| `test` | `main.py:1775`, `dispatch_test` `main.py:1871` | Server-seeded known-answer GPU workload | **Signature + known-answer hash** | FUNCTIONAL — closest existing analog to `pytorch-matmul-v1` |
| `benchmark` | `main.py:1779` | GPU benchmark | Signature (no known-answer compare shown) | PARTIAL — verify what the platform checks |
| `render` | `main.py:1781` | Blender frame job | Signature + output hash | FUNCTIONAL (batch, egress none) |
| `transcode` | `main.py:1785`, `/transcode` `main.py:3753` | FFmpeg segment transcode | Signature + output hash | FUNCTIONAL (batch, egress none) |
| `stitch` | `main.py:1789` | FFmpeg stitch | Signature + output hash | FUNCTIONAL (batch) |
| `notebook` | `main.py:1773` | Run arbitrary notebook code | Signature only | **UNSAFE as a buyer-facing "validated job"** — arbitrary code execution; fine only as an owner/interactive tool |
| `template` | `main.py:1793` | Launch a `TEMPLATES` container | Signature | see container table |
| `vm` | `main.py:1802` | Launch a VM, report connection | connection details | FUNCTIONAL (interactive VM rental) |

---

## Classification against the task's required buckets

The task requires every buyer-visible template to end as
`WORKING_AND_TESTED` / `HIDDEN_PENDING_FIX` / `REMOVED`, with ≥1
`WORKING_AND_TESTED` **on the real GPU**.

**This cannot be satisfied from this environment** because "tested on the real
GPU" is impossible without access to the seller Droplet. The honest current
state is:

- **Candidate for `WORKING_AND_TESTED` once GPU access exists:** the `test`
  task type and the `ffmpeg`/`blender` batch templates (deterministic, egress
  `none`, signature + hash validated). The `test` type is the recommended first
  proof because it already has server-side known-answer validation.
- **`HIDDEN_PENDING_FIX` candidates for a *validated-job* marketplace:** `notebook`
  and `pytorch` (base image) should not be presented as deterministic validated
  jobs; they are interactive/BYO-script.
- **`REMOVED`:** none recommended blindly. No template is provably broken from
  code review; removal needs live evidence.

## Required next step — live verification matrix (run when access exists)

For each buyer-visible template, from the buyer Droplet against
`https://petabyte.market`, capture: dispatch → agent claim (`/jobs/next`) →
container pull + digest → GPU execution (`nvidia-smi` shows utilisation) →
signed result (`/jobs/result`) → validation state → escrow release. Only a
template with that full chain captured may be marked `WORKING_AND_TESTED`.
