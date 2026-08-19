# Billing model — per-hour capacity vs per-token inference

Petabyte deliberately uses **two** billing units, because it sells two different things.

## 1. Capacity rental → **per hour** (`/launch`, `request_vm`, VMs, clusters, disk, render, training)

You rent a whole GPU / reserved units for a window and run *anything*. Per-hour is correct here
for four reasons:

1. **Heterogeneous workloads.** Renders, training runs, notebooks, game servers, transcodes —
   most have no notion of "tokens". Time is the only unit that spans the whole catalog.
2. **Untrusted hardware.** Sellers are strangers' GPUs. A token count would be **self-reported**
   by the seller — a direct incentive to inflate it or serve a smaller model. The whole trust
   model exists to *not* trust seller self-reports. Wall-clock, by contrast, is
   **platform-measured** (`assigned_at → completed_at`) and can't be inflated. And LLM outputs
   with sampling aren't reproducible, so there's no hash-compare quorum to verify tokens (that's
   why the `test` task uses integer known-answers).
3. **Seller cost is time.** The GPU is occupied and drawing power for the window regardless of
   how many tokens you send; the seller can't re-rent it. Per-hour aligns the buyer's payment
   with the seller's opportunity cost. Per-token would push utilization risk onto sellers, who
   own the hardware — they'd delist.
4. **Clean escrow.** Per-hour has a known max at booking → escrow the max, refund unused hours.
   Per-token is open-ended → live holds, streaming meters, spend caps, more dispute surface.

## 2. Managed inference → **per token** (`/v1/chat/completions`, the Inference API)

Send a prompt, get an answer, pay for tokens. Per-token is correct here because all three
conditions per-hour fails are now met:

1. The workload **is** LLM text generation — tokens are the natural unit.
2. **Petabyte controls the runtime**, so *we* count tokens from the response. The count is
   trustworthy, not seller-claimed.
3. It's **bursty, shared, no-commitment** — a caller shouldn't rent a whole hour to ask one
   question.

See `docs/INFERENCE_API.md`.

## The arbitrage (why we do both, not one)

> Rent GPU capacity from sellers **per hour** (keeps seller economics + the trust model intact)
> → keep a **warm pool** running a model → resell it to buyers **per token**.

Seller-facing settlement stays per-hour and verifiable; the buyer-facing product is per-token
pay-per-use; Petabyte captures the **utilization gap** (you paid for the hour, you sell the
tokens of everyone who shared it). That's the Together/Fireworks model and a better margin story
than the raw 10% marketplace take.

Per-token could only reach **seller** settlement if the token count were trustworthy on the
seller's box — which needs **Petabyte-operated pools** (we run the node) or **TEE attestation**
of the inference (roadmap). Until then: per-hour to sellers, per-token to buyers.
