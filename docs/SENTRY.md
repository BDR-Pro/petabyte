# Sentry error tracking

Sentry captures unhandled exceptions, 5xx failures, and error-level logs across the Petabyte
FastAPI service. It **complements** the existing stack (Prometheus metrics, Loki logs, Tempo
traces, OpenTelemetry, structured logging) — it does not replace any of it — and it is **never a
hard dependency**: if Sentry is unconfigured, unreachable, or broken, the API, payments, GPU jobs,
auth, the database and payouts all continue to work.

## Where it lives

Sentry initialises in the **one** central observability bootstrap, alongside logging, metrics and
tracing:

```
os.getenv("SENTRY_DSN")
  -> lumaris_api/observability.py : init_observability() -> init_sentry()
  -> sentry_sdk.init(... before_send=_sentry_scrub ...)
```

`init_observability()` is called once at API startup (`lumaris_api/main.py`). There is no
`sentry_sdk.init()` anywhere else.

## Enabling / disabling

Sentry is **active only when a DSN is present and it is not disabled**:

| Variable | Default | Meaning |
|---|---|---|
| `SENTRY_DSN` | *(empty)* | Sentry ingest DSN. **Empty → Sentry is off** (app still starts). Never hard-code it. |
| `SENTRY_ENABLED` | `true` | Master off-switch. `false` disables Sentry even if a DSN is set. |
| `SENTRY_ENVIRONMENT` | `ENVIRONMENT` (`development`) | Sentry environment label (`test`, `staging`, `production`). |
| `SENTRY_RELEASE` | `RELEASE` / `GITHUB_SHA` | Release tag for grouping/regressions. |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Performance-trace sampling (conservative). |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0.0` | Profiling off unless explicitly raised. |
| `SENTRY_MAX_BREADCRUMBS` | `30` | Breadcrumb ring size. |

**Disable Sentry:** leave `SENTRY_DSN` empty, or set `SENTRY_ENABLED=false`.

These are declared in `lumaris_api/template.env` and the GitHub config manifest
(`config/github_configuration_manifest.yaml`, `platform`/`observability` scope), so they flow
through the normal deploy path (`ENV_VARS` + Secrets → `generate_deploy_env.py` →
`/etc/lumaris/lumaris.env` → systemd → the Python process).

## Integrations enabled

FastAPI + Starlette (request transactions; **only 5xx** become error events — ordinary
400/401/403/404/409/422 are expected control flow and are dropped), SQLAlchemy (DB spans/errors),
logging (`INFO`+ → breadcrumbs, `ERROR`+ → events), and threading (context propagation to
background threads). No integrations for frameworks Petabyte doesn't use.

## Security / redaction

Sentry runs with `send_default_pii=False` (no auto-captured headers, cookies, IP or body) and a
`before_send` scrubber (`_sentry_scrub`) that **reuses the same central redactor as our logs**
(`redact()` / `_mask_value` in `observability.py`) — there is one sanitizer, not several. It:

- drops **expected 4xx** HTTPExceptions (no noise);
- removes request **cookies**, redacts **headers**, **body** and **query string**;
- drops **user identity** (email is PII);
- recursively redacts `extra` / `contexts` / `tags` / breadcrumbs by key and value;
- masks secret-shaped values in messages and exception text — Stripe keys (`sk_/rk_/whsec_`),
  PaymentIntent `client_secret`, `Bearer` tokens, JWTs, PANs, emails;
- **fails closed**: if scrubbing itself errors, the event is dropped rather than sent.

Never sent: Authorization/Bearer/JWT, cookies/sessions, passwords/hashes, API keys (incl. seller
keys), `SECRET_KEY`, `SERVER_PRIVATE_KEY`, private keys, Stripe secret/webhook secrets, PaymentIntent
`client_secret`, OAuth tokens, `DATABASE_URL`/DB passwords, Mailgun keys, the Sentry DSN, banking/KYC
data, SSNs/gov IDs, raw card data, connected-account secrets, or environment dumps. Proven by
`lumaris_api/sentry_test.py`.

Safe identifiers that DO travel (as Sentry tags/context, useful for triage): transaction public id,
payment intent id, transfer id, seller internal id, spec id, task id, booking id, payment mode,
currency, state transition.

## Correlation with Grafana / Loki / Tempo

`before_send` copies the current correlation ids (`trace_id`, `request_id`, `transaction_id`,
`task_id`, `payment_mode`) from the logging context onto the Sentry event as tags. From a Sentry
error you can take the `trace_id` straight to Tempo, and the ids to Loki/Grafana, to see the same
request/job across the whole stack.

## Seller agent — intentionally NOT integrated

The seller agent (`lumaris_agent/`) is **not** wired to Sentry. The server DSN is a server-side
credential; shipping it to seller machines would expose it, and the deploy generator's GPU-node
deny-list already refuses to write `SENTRY_DSN` into a seller env (`scripts/generate_deploy_env.py`).
Seller-side errors remain observable via the agent's structured logs → Loki. If seller-side Sentry
is ever wanted, it must use a **separate, seller-scoped DSN** provisioned for that purpose — not the
platform DSN.

## TEST configuration (test.petabyte.market)

`SENTRY_DSN` is a **non-secret key inside the `ENV_VARS` bundle** (Repository Variable) — the same
place all non-secret config lives — not an individual `vars.SENTRY_DSN` and not a Secret. Because
`SENTRY_DSN` is a platform-scoped manifest variable, the normal platform deploy
(`generate_deploy_env.py --target platform`) already writes it into the server env file, so the
running service picks it up automatically. Set `SENTRY_ENVIRONMENT=test` (and, if you want, a fixed
`SENTRY_RELEASE`) alongside it in `ENV_VARS` for the TEST server.

The TEST verification workflow (`sentry-verify-test.yml`) binds to `environment: TEST`, resolves
`SENTRY_DSN` out of `${{ vars.ENV_VARS }}`, masks it, then sends one event:

```yaml
jobs:
  verify-sentry-test:
    environment: TEST
    env:
      SENTRY_ENVIRONMENT: test
      SENTRY_RELEASE: ${{ github.sha }}
    steps:
      - name: Resolve + mask SENTRY_DSN from ENV_VARS   # parses vars.ENV_VARS, ::add-mask::, GITHUB_ENV
        ...
```

Production is configured independently — do not point production at the TEST DSN.

## How to verify (send ONE test event)

Two safe options — **no unrestricted crash endpoint exists**:

1. **CI (recommended):** run the **“Verify Sentry (TEST)”** workflow
   (`.github/workflows/sentry-verify-test.yml`) via *Actions → Run workflow*. It runs the offline
   unit tests, then `python scripts/sentry_selftest.py --send`, emitting one event to the TEST
   project (environment `test`, release = commit SHA). The DSN is masked and never printed.

2. **On the running TEST service (admin-only):** `POST /admin/observability/sentry-test` as an
   admin. It captures one benign event and returns the event id. It is **404 in production** and
   409 if no DSN is configured — it can never be an abuse surface.

Then open Sentry → your project → environment `test` and confirm the event appears.

## How releases work

`SENTRY_RELEASE` defaults to `RELEASE` (`RELEASE_VERSION` / `PETABYTE_RELEASE_SHA` / `GITHUB_SHA`).
In CI it is set to `${{ github.sha }}`; on the server, set it at deploy time (or let it fall back to
the build SHA). Consistent release tags let Sentry group regressions and mark “resolved in next
release”.
