# Inference API — pay-per-token, OpenAI-compatible

> **Status: working, priced-off by default.** `POST /v1/chat/completions` returns real
> completions and bills the caller's wallet per token when pricing is set. Prices default to 0
> (free) so you can dial them in. The model runs on the configured inference pool
> (`EDGE_INFER_UPSTREAM_URL`); sellers are still settled **per hour** for that GPU capacity, so
> the per-token charge is the **resale margin** (the Together/Fireworks model).

## Why per-token here but per-hour for `/launch`

`/launch` rents a *whole machine* for a window — heterogeneous workloads (render, train,
notebooks, game servers) with no "tokens", on **untrusted** seller hardware where a
self-reported token count would be a fraud vector, and where the seller's cost is *time*. So
capacity is billed per **hour** (platform-verifiable wall-clock).

The Inference API is the opposite shape: LLM-only, **Petabyte controls the runtime** (so *we*
count tokens from the response — trustworthy), bursty and shared, no commitment. That's exactly
where per-token fits. See `docs/BILLING_MODEL.md` for the full reasoning.

## Endpoint

```
POST /v1/chat/completions        # OpenAI-compatible
X-API-KEY: <an inference-scoped key>     # mint at /create_api_key?scopes=inference
Content-Type: application/json

{ "model": "llama3.2",
  "messages": [{"role":"user","content":"what is petabyte?"}],
  "max_tokens": 512 }
```

Also accepts a bare `{"prompt": "..."}` as a convenience (becomes one user message). Response is
the upstream's OpenAI-shaped body plus an `x_petabyte` block:

```json
{ "model": "llama3.2",
  "choices": [{"message": {"role":"assistant","content":"Petabyte is a verified GPU marketplace."}}],
  "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
  "x_petabyte": {"billed": true, "charged": 0.00016, "tokens": 20,
                 "prompt_tokens": 12, "completion_tokens": 8,
                 "price_per_mtok_in": 5.0, "price_per_mtok_out": 15.0} }
```

Point any OpenAI SDK at `<base>/v1` (auth via `X-API-KEY`; `Authorization: Bearer` support is a
follow-up).

## Billing

- Charge = `prompt_tokens/1e6 * INFERENCE_PRICE_PER_MTOK_IN + completion_tokens/1e6 * INFERENCE_PRICE_PER_MTOK_OUT` (USD).
- Debited from the caller's **wallet balance** via `charge_wallet` → a balanced double-entry
  ledger posting (`entry_type="inference"`, credit to `PLATFORM_REVENUE`, kept in lockstep with
  the `Platform.revenue` scalar). Revenue is reconstructible from the books.
- **Pre-check:** before the model runs, the wallet is checked against an *upper-bound* estimate
  (prompt-length heuristic + `max_tokens`); if it can't cover it, the call is refused **402**
  before any work is done — unpaid work is never given away. The actual charge (≤ estimate) is
  applied after generation.
- Pricing `0` (default) → free and unbilled.
- Monthly usage is tallied per account in `ApiUsage` (shared with the data API).

## Config

| Key | Default | Meaning |
|---|---|---|
| `EDGE_INFER_UPSTREAM_URL` | — | OpenAI-compatible pool the request is served by (a `petabyte launch ollama` node). Required; `503` if unset. |
| `EDGE_INFER_MODEL` | — | Default model when the caller omits one. |
| `EDGE_INFER_UPSTREAM_TOKEN` | — | *(secret)* optional bearer for the upstream. |
| `INFERENCE_PRICE_PER_MTOK_IN` | `0` | USD per 1M input tokens. |
| `INFERENCE_PRICE_PER_MTOK_OUT` | `0` | USD per 1M output tokens. |

## Auth & limits

- `inference`-scoped API key via `X-API-KEY` (the published data-API **sandbox key** also works,
  free and unmetered, for trying the flow). Missing scope → `403`; bad key → `401`.
- Per-IP abuse cap (600/hr) on top of the wallet throttle; prompt capped at 32k chars,
  `max_tokens` clamped to 4096.
- Upstream errors return `502` and never leak the upstream URL/token.

## Turn it on

```bash
petabyte launch ollama --hours 4         # warm a GPU pool (seller paid per hour)
# API env (ENV_VARS):
EDGE_INFER_UPSTREAM_URL=<pool base URL>
EDGE_INFER_MODEL=llama3.2
INFERENCE_PRICE_PER_MTOK_IN=5
INFERENCE_PRICE_PER_MTOK_OUT=15
# a developer mints a key:
curl -X POST "$API/create_api_key?scopes=inference" -H "Authorization: Bearer <jwt>"
```

## Known gaps (next steps)

- **Keep-warm pool + auto-launch/scale** instead of a single static upstream, and route to the
  cheapest eligible node — so the per-hour supply cost is minimized under the per-token resale.
- **`Authorization: Bearer` key auth** for drop-in OpenAI-SDK compatibility.
- **Streaming** (`stream:true`) with incremental token metering.
- **Pre-authorized holds** instead of the estimate pre-check, to remove the rare
  charge-after-generation balance race.
- **TEST/LIVE isolation** on inference charges (today it debits the dollar wallet directly).
