# Database migrations (Alembic)

> Config: [`lumaris_api/alembic.ini`](../lumaris_api/alembic.ini) ·
> Env: [`lumaris_api/alembic/env.py`](../lumaris_api/alembic/env.py) ·
> Revisions: `lumaris_api/alembic/versions/`

## The model

The schema comes from the SQLAlchemy models in `db.py` (`Base.metadata`). There are **two ways** it
reaches a database, and they share that single source so they can't disagree:

1. **Runtime bootstrap** — on import, `db.py` runs `init_db()` (`create_all` + idempotent
   `_ensure_columns` / `_ensure_check_constraints` / `_ensure_indexes`). This is what dev, the
   hermetic test suites, and the app process use. Fast, no tooling.
2. **Alembic** — `alembic upgrade head` applies versioned, **reviewed and CI-tested** migrations.
   The baseline (`0001_baseline`) reproduces the exact `init_db()` schema, so upgrading an empty DB
   yields the same schema `create_all` builds. This is the **change-management + audit** layer.

Alembic sets `PETABYTE_SKIP_INIT_DB=1` in its `env.py` so importing `db` during a migration does
**not** trigger the import-time bootstrap — Alembic owns schema creation for that run. In all other
contexts the flag is unset and the bootstrap runs as before.

## CI gate

The **"postgres (the one that counts)"** job runs, on a real Postgres:

```
alembic upgrade head      # build the full schema on an empty DB
alembic downgrade base    # drop it
alembic upgrade head      # re-apply (repeatable)
```

So every migration is proven **applyable and reversible on Postgres** before it can reach a deploy —
SQLite can't exercise the FK/constraint DDL that production depends on.

## Adding a migration

1. Change the models in `db.py`.
2. Autogenerate a revision (against a DB already at head):
   ```bash
   cd lumaris_api
   DATABASE_URL=postgresql+psycopg2://…/yourdb alembic revision --autogenerate -m "add X to Y"
   ```
3. **Review the generated `upgrade()`/`downgrade()`** — autogenerate is a draft, not gospel
   (it misses some server defaults, CHECK constraints, and data migrations). Edit as needed.
4. `alembic upgrade head` locally, confirm, then `alembic downgrade -1` and re-upgrade to prove
   the down path. Commit the revision file. CI re-runs up/down on Postgres.

## Adopting Alembic on an existing database

A DB whose schema was built by the runtime bootstrap already matches `0001_baseline`. Tell Alembic
it's current without re-running the baseline:

```bash
alembic stamp head
```

Then apply future migrations normally with `alembic upgrade head`.

## Deploy

`deploy/update.sh` runs `alembic upgrade head` when revisions are present (see that script). The
runtime bootstrap still runs on service start as a backstop, so a fresh box is never left without a
schema even before the migration step. Making Alembic the *sole* authority (dropping the bootstrap)
is a deliberate future step once every environment is stamped and the CI gate has proven the chain
across a few real migrations.
