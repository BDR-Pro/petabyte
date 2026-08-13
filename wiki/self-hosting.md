# Self-hosting

Petabyte is a normal FastAPI app. It starts with a database URL and a couple of secrets; everything
else is optional and lights up when configured.

## Run it (dev)

```bash
cd lumaris_api
pip install -r requirements.txt
export SECRET_KEY=dev-secret
export DATABASE_URL=sqlite:///./petabyte.db
uvicorn main:app --reload --port 8000
# open http://localhost:8000  (site) and http://localhost:8000/console (app)
```

Docker: a `Dockerfile` and `docker-compose.yml` are in the repo root. The database schema is created
on startup (`init_db()`), and new columns are forward-migrated automatically — no manual migration
for the features documented here.

## Configuration

All settings are environment variables. The authoritative list with defaults and descriptions is
**`lumaris_api/template.env`**; a generated manifest lives in `config/`. A **drift check**
(`scripts/check_configuration_drift.py`, run in CI) guarantees every variable the code reads is
documented — so this never goes stale.

Essentials to start:

| Var | Purpose |
|---|---|
| `SECRET_KEY` | signs sessions/tokens (required) |
| `DATABASE_URL` | `sqlite:///…` for dev, `postgresql://…` for production |
| `SERVER_PRIVATE_KEY` | Fernet key for encrypting secrets at rest |

Common optional groups (all degrade safely if unset):

- **Object storage** (backups, persistent volumes, job I/O): `S3_BUCKET`, `S3_REGION`, `S3_SSE`, AWS
  creds; `S3_STUB=true` writes to a local dir for dev/tests.
- **Model hub**: `PETABYTE_HOME` (cache root), `MODEL_PULL_ENABLED` (opt-in server-side pulls),
  `MODEL_MAX_PULL_GB`, `HF_ENDPOINT`, `HF_TOKEN`. See [Models](models.md).
- **Payments**: Stripe keys + `PAYMENTS_LIVE_ENABLED` to go beyond TEST MODE (fails safe if
  inconsistent). See [Payments & trust](payments-and-trust.md).
- **Observability** (optional): Prometheus metrics, OTel tracing, Sentry, Redis — import-guarded, so
  absent = cheap no-op.
- **Email / GeoIP / newsletter**: optional integrations for verification, data-residency, signups.

## The remote-execution environment

If you're using Petabyte's hosted **Claude Code on the web** environment, note it's ephemeral: the
repo is cloned fresh per session and the container is reclaimed after inactivity, so commit and push
anything worth keeping. Outbound network is governed by the environment's policy. This doesn't affect
self-hosting your own Petabyte instance — it's about the dev environment only.

## Deploying

`deploy/` contains the deploy script and env generator (scope-filtered so a node only gets the vars
it needs). See `deploy.md` and the runbooks under `docs/` (backup/restore, incident triggers,
sync procedures). The health endpoints are `/healthz` (liveness) and `/readyz` (readiness).

## Tests

The suite is hermetic and offline. Notable ones: `smoke_test.py` (end-to-end API), `demo_test.py`,
`modelhub_test.py` (model hub against a real local HTTP server), `volumes_test.py` (persistent
storage), plus frontend contract audits (`audit_js.py`, `audit_frontend.py`) and the config-drift
check. All run in CI.
