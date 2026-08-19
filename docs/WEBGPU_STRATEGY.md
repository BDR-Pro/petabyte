# WebGPU strategy — decision record

Three WebGPU ideas were evaluated for Petabyte. This records what we built, what we deferred,
and why — so the reasoning survives.

## The constraint that drives every answer

WebGPU is a real browser compute API (WGSL shaders; WebLLM / transformers.js run real models),
but it collides with the two things Petabyte is built on:

1. **No CUDA.** Buyers rent Ollama/vLLM/PyTorch/Blender-OPTIX. None of that runs in WebGPU — only
   WebGPU-native kernels/models do. It's a *different* workload class.
2. **It can't identify or attest hardware.** `requestAdapterInfo()` is privacy-redacted; a tab
   can't hold a signing key. So any browser result is the *lowest* trust tier and spoofable —
   the opposite of the verified-compute moat.
3. **Memory/feature-capped & ephemeral.** ~128–256 MiB default buffers, no FP64, tensor cores
   not exposed, throttled when backgrounded, gone on tab close.

## Decisions

| Idea | Decision | Why |
|---|---|---|
| **1. In-browser self-benchmark** (`/test`, `/benchmark` for users) | ✅ **Shipped** as `/mysystem` | Great zero-install onboarding funnel. CSP-clean (pure WGSL, no external fetch). Kept strictly separate from the attested `benchmark` task type — labelled indicative, never feeds trust/pricing. |
| **3. WebGPU + API to "monetize webapps instead of ads"** | ✅ **Shipped (reframed) as the Edge-Inference SDK** | The literal "mine the visitor for ad-replacement" is Coinhive 2.0 — blocked by browsers/AV, consent/legal risk, unverifiable, bad economics. **Reframed** to: run the visitor's *own* AI feature on their WebGPU (free to the site) with a **metered Petabyte-GPU fallback** — consent-based, on-strategy, monetized via the API. See `docs/EDGE_INFERENCE.md`. |
| **2. WebGPU "mine" as another seller channel** | 🚫 **Shelved** | Can't run the marketplace's CUDA jobs; browser sellers are the lowest, spoofable trust tier (reintroduces the pay-for-unverified-work risk we closed); sub-cent, Sybil-prone economics. It works *against* the verified-compute story we raise on. Only viable shape would be a separate, opt-in, credits-not-cash, quorum-verified network — a distinct R&D bet, not "another way to run the agent." |

## What shipped (this branch)

- **`/mysystem`** — pure-WGSL matmul benchmark → rough GFLOP/s + adapter info + memory limits,
  with a loud "indicative only, can't identify your GPU" caveat and an `/install` CTA. No CSP
  change, no external anything.
- **Edge-Inference SDK** — `lumaris_api/static/petabyte-edge.js`, demo at `/edge`, fallback
  `POST /edge/infer` (prototype responder), on-device path gated behind `EDGE_INFERENCE_ENABLED`
  (default off; see `docs/EDGE_INFERENCE.md` for the CSP rationale).

## Guardrails that must not regress

- `/mysystem` must **never** write to `benchmark_verified` or influence pricing — it's a browser
  number, not an attested one. The trust ladder stays attested-node-only.
- `/edge/infer` must never present a canned string as a real model completion — keep the
  `prototype: true` flag until it's wired to a real GPU.
- On-device inference stays **opt-in** (`EDGE_INFERENCE_ENABLED=false` by default) so the main
  app's CSP stays locked down.
