# API & keys

Petabyte is API-first. The website, console and CLI all call the same HTTP API, and you can too.

## The docs environment (Scalar)

Interactive references are rendered with **Scalar** (the same environment this wiki is served in):

| Portal | What it covers | URL |
|---|---|---|
| **Full API** | Everything, generated from the live OpenAPI schema | `/docs` |
| **Developer API** | Build/compute: rent GPUs, run jobs, wallet, marketplace, account | `/devs` |
| **Data API** | Buy data: price index, supply, demand, GPU-authenticity dataset | `/data` |
| **This wiki** | New-user guide, same Scalar shell | `/wiki` |

Raw schemas: `/openapi.json` (full), `/devs/openapi.json`, `/data/openapi.json`. Each portal is
backed by a **tag-filtered** copy of the schema, so the two products never overlap.

## Two products, two key types

- **Compute/agent keys** carry `node` / `jobs` scopes — for renting GPUs and running jobs.
- **Data keys** carry the `data` scope — for the metered data API.

A key for one product is refused by the other. That separation is enforced server-side, not just in
docs.

## Getting a key

- **Console → Access → Create key**: give it a label, an expiry, and optional scopes. The full key is
  shown **once** — copy it then. Revoke any time. (See [Teams & security](teams-and-security.md).)
- Programmatic clients send it as `X-API-KEY: <key>`. Interactive/session calls use a bearer token
  from `/login` (`Authorization: Bearer <token>`).

## Auth quickstart

```bash
# session token (what the CLI uses)
curl -s -X POST $API/login -d 'username=alice&password=…' | jq -r .access_token

# API key
curl -s $API/verify_api_key -H "X-API-KEY: $KEY"
```

## The Data API (metered)

Pay-as-you-go over live marketplace data — a benchmark-anchored price index, price history,
cloud-savings, live supply, demand, workload mix, templates bought, and the GPU-authenticity
dataset. There's a free monthly allowance and a keyless `sample` endpoint to see every response
shape first. Full details + pricing render at **`/data`**.

## Rate limits, errors, request IDs

Errors come back in a consistent envelope with a machine-readable `code`, a human `message`, and a
`request_id` you can quote in support. Transient conditions (429/5xx) are safe to retry with backoff.

## Models over the API

The model hub is also an API — search, info, availability, and (opt-in) server-side pull with live
progress. See [Models](models.md) and `docs/models.md` for the endpoint list.
