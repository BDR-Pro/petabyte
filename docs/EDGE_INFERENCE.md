# Edge Inference SDK (`petabyte-edge.js`)

> **Status: developer preview.** The client SDK and the browser demo are real. The paid fallback
> (`POST /edge/infer`) **returns real completions when an operator points it at an
> OpenAI-compatible upstream** (`EDGE_INFER_UPSTREAM_URL` — e.g. a Petabyte-launched ollama/vLLM
> node); with no upstream configured it returns a clearly-labelled placeholder. Nothing here
> fakes a real completion. The remaining production step is per-token **billing** of the site's
> developer account (see below).

## What it is

A one-file JavaScript SDK that lets any website add an AI feature that runs **on the visitor's
own GPU** via WebGPU — free to the site — and **falls back to a metered Petabyte GPU** through
the API when the visitor has no capable GPU.

This is the consent-based inverse of "mine the visitor's GPU to replace ads": the user asked for
the AI feature, their own device serves it, and Petabyte only earns on the paid fallback. It is a
monetization *and* cost-reduction story for the API, not an ad-replacement gimmick — and it does
not touch the marketplace's verified-compute trust model.

- **SDK:** [`lumaris_api/static/petabyte-edge.js`](../lumaris_api/static/petabyte-edge.js) — served at `/static/petabyte-edge.js`.
- **Demo page:** `/edge` (`EDGE_HTML` in `pages.py`).
- **Self-benchmark (sibling feature):** `/mysystem` — a CSP-clean, pure-WGSL "test your GPU"
  page that funnels prospective sellers to `/install`. See `docs/WEBGPU_STRATEGY.md` for how the
  two relate.
- **Fallback API:** `POST /edge/infer` (`main.py`).

## Integration (three lines)

```html
<script src="https://petabyte.market/static/petabyte-edge.js"></script>
<script>
  PetabyteEdge.configure({ apiBase: 'https://petabyte.market', model: 'onnx-community/Qwen2.5-0.5B-Instruct' });
  const r = await PetabyteEdge.infer('Summarize: ' + text);   // r.source = 'on-device' | 'petabyte'
</script>
```

### API

| Call | Returns | Notes |
|---|---|---|
| `PetabyteEdge.configure({apiBase, model, allowOnDevice, maxTokens, transformersUrl})` | merged config | call once |
| `PetabyteEdge.capabilities()` | `{webgpu, f16, adapter}` | cheap, side-effect-free |
| `PetabyteEdge.infer(prompt, opts?)` / `infer({prompt, ...})` | `{source, model, text, meta?}` | tries on-device, then fallback |

`opts`: `{ model, maxTokens, allowOnDevice, apiBase, onProgress(p), onFallback(err) }`.
`source` is `'on-device'` when the visitor's GPU served it, `'petabyte'` when the API fallback did.

## The decision flow

```
infer(prompt)
  ├─ allowOnDevice && navigator.gpu present?
  │     ├─ yes → load @huggingface/transformers (WebGPU) → generate → source:'on-device'  ($0 to the site)
  │     │         └─ any failure (CSP/no-weights/OOM) ─┐
  │     └─ no ──────────────────────────────────────── ┤
  └─ fallback: POST /edge/infer  ────────────────────── ┴─→ source:'petabyte'  (metered)
```

The fallback path always works and is same-origin (`connect-src 'self'`), so the SDK is useful
even with on-device inference turned off.

## CSP: why on-device is opt-in

Running a model in the browser needs three things the **locked-down default CSP forbids**:

1. **WASM compilation** — `script-src 'wasm-unsafe-eval'` (onnxruntime-web).
2. **Blob workers** — `worker-src 'self' blob:` (transformers.js spins workers).
3. **Model-weight fetches** from the model host — `connect-src https://huggingface.co …`.

The default policy is `connect-src 'self'` with no `wasm-unsafe-eval` and no `blob:` — deliberately,
because a broad `connect-src` reintroduces a data-exfiltration channel. So on-device inference is
gated behind **`EDGE_INFERENCE_ENABLED`** (default `false`):

- **`false` (default, production-safe):** CSP unchanged; the SDK/demo use the `/edge/infer`
  fallback. The demo's "try on-device" checkbox will attempt to load the lib and then fall back.
- **`true`:** the response middleware widens the CSP (adds `'wasm-unsafe-eval'` + `blob:` to
  `script-src`, a `worker-src 'self' blob:`, and the model host + jsdelivr to `connect-src`), so
  true on-device inference works.

Set it per environment via `ENV_VARS` (it's in `config/github_configuration_manifest.yaml` and
`template.env`). Turning it on is a deliberate CSP trade-off — do it on the surface that needs it,
and prefer a dedicated subdomain if you want to keep the main app's CSP tight.

## Fallback: real inference via a configured upstream (implemented)

`POST /edge/infer` validates + rate-limits (60/hr/IP, 8000-char cap), then:

- **If `EDGE_INFER_UPSTREAM_URL` is set** → it POSTs an OpenAI-compatible chat completion to
  `<upstream>/v1/chat/completions` (`{model, messages, max_tokens≤2048, stream:false}`), with an
  optional `Authorization: Bearer <EDGE_INFER_UPSTREAM_TOKEN>`, and returns the **real** result
  (`{source:'petabyte', prototype:false, model, text, usage}`). The upstream URL is **operator
  config, never client-supplied**, so it is not an SSRF sink; the client only supplies `prompt`
  and `model` (validated). Upstream errors return `502` and never leak the URL/token.
- **If it's unset** → it returns the labelled placeholder (`prototype:true`).

### Point it at a Petabyte-launched ollama node

```bash
petabyte launch ollama --hours 4            # book the cheapest verified GPU, start ollama
# then, in the API env (ENV_VARS):
EDGE_INFER_UPSTREAM_URL=<the node's OpenAI-compatible base URL>   # ollama exposes /v1/chat/completions
EDGE_INFER_MODEL=llama3.2                    # default model when the caller doesn't specify
EDGE_INFER_UPSTREAM_TOKEN=                   # (secret) only if the node requires a bearer
```

Any OpenAI-compatible server works (ollama, vLLM, or a hosted endpoint) — this is the seam that
makes on-device *and* server inference share one client call.

### Remaining production step — per-token billing

The proxy path is live, but it does **not yet meter/charge** the site's developer account. To
close the loop: resolve the caller's developer key (`/keys`), meter tokens/seconds from the
`usage` block, post the charge through the existing ledger with TEST/LIVE isolation, and (for a
Petabyte-native pool) auto-launch/keep-warm nodes instead of a single static upstream.

## Security notes

- The fallback endpoint is **public and per-IP rate-limited**; prompt is capped at 8000 chars.
- On-device inference keeps the prompt on the device (privacy win); the fallback sends it to the
  API, so document that to your users.
- Do **not** enable `EDGE_INFERENCE_ENABLED` on a surface that also renders untrusted
  user-generated HTML without re-reviewing the CSP widening.
