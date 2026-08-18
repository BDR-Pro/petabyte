# Database backup & disaster recovery — runbook

> Code: [`lumaris_api/backup.py`](../lumaris_api/backup.py) ·
> CLI: [`scripts/backup_database.py`](../scripts/backup_database.py) ·
> Tests: [`lumaris_api/backup_test.py`](../lumaris_api/backup_test.py)

Backs up the **platform database** — users, bookings, the money ledger, listings — to AWS S3 (or
any S3-compatible store) so it can be restored after data loss. This is distinct from **job
snapshots** (`Checkpoint`), which back up a *buyer's running job volume* and are uploaded by the
node via presigned URLs.

## What a backup is

Each run does: **dump → gzip → sha256 → upload one object → record a row → prune old backups**.

- **Dump** — `pg_dump --format=plain` for Postgres; SQLite `iterdump()` for the dev/offline engine.
  Both are portable SQL that restores by replay.
- **Object** — `s3://$S3_BUCKET/<BACKUP_S3_PREFIX>/<environment>/<timestamp>-<sha8>.sql.gz`,
  server-side encrypted (`S3_SSE`, default `AES256`).
- **Row** — a `database_backups` row records the key, `s3_uri`, engine, size, **SHA-256** of the
  compressed object, and status (`ok`/`failed`). The bytes live in S3; the DB holds only the
  reference + integrity hash.
- **Prune** — only the newest `BACKUP_RETENTION` (default 30) successful backups are kept; older
  objects **and** their rows are deleted.

Every attempt is recorded. A failed dump/upload writes a `status=failed` row so monitoring can
alert on "no successful backup in N hours".

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `BACKUP_ENABLED` | `true` | set `false` to hard-disable (the runner then refuses and exits non-zero) |
| `S3_BUCKET` | — | **required** target bucket (reused from object storage config) |
| `BACKUP_S3_PREFIX` | `db-backups` | key prefix inside the bucket |
| `BACKUP_RETENTION` | `30` | keep only the newest N successful backups |
| `BACKUP_DUMP_TIMEOUT_S` | `1800` | hard timeout for the `pg_dump` subprocess |
| `PG_DUMP_BIN` | auto | explicit `pg_dump` path if not on `PATH` (also auto-discovers `/usr/lib/postgresql/*/bin`) |
| `S3_SSE` | `AES256` | server-side encryption (`""` disables; `aws:kms` is AWS-only) |
| `S3_STUB` | — | `true` writes to a local dir instead of S3 (tests / dry-run) |

**Bucket hardening (do this):** the object is a full logical dump — treat the bucket as sensitive.
Make it **private**, enable **versioning** and **default encryption**, add a **lifecycle policy**
(e.g. transition to Glacier + expire), and restrict IAM to `s3:PutObject`/`GetObject`/`ListBucket`/
`DeleteObject` on `arn:aws:s3:::<bucket>/<prefix>/*` only.

## Scheduling (cron / systemd)

Run the backup on the API host, where `DATABASE_URL` + `S3_*` are already in the environment.
Which command depends on how you deployed:

**A. Repo checkout / production Docker image** (the image ships `pg_dump` and the full repo, so
`scripts/backup_database.py` is present). Drive the CLI directly — it expects to sit next to
`lumaris_api/`, so run it from the checkout root:

```cron
# /etc/cron.d/petabyte-db-backup  — hourly
0 * * * *  petabyte  . /etc/lumaris/lumaris.env && \
    cd /path/to/petabyte && .venv/bin/python scripts/backup_database.py --verify \
    >> /var/log/petabyte-backup.log 2>&1
```

**B. `deploy.sh` droplet** — that path rsyncs only `lumaris_api/` into `/opt/lumaris`, so the
repo-root `scripts/` CLI is **not** deployed there. Drive the admin endpoint from any scheduler
instead:

```cron
0 * * * *  root  curl -fsS -X POST -H "Authorization: Bearer $PETABYTE_ADMIN_TOKEN" \
    https://yourdomain.com/admin/backups/run \
    >> /var/log/petabyte-backup.log 2>&1
```

`POST /admin/backups/run` is admin-gated and takes an optional `retention` query param; it returns
the backup summary (or 503 with the reason, which also records a `status=failed` row so alerts fire).
Integrity-verify a stored backup with the follow-up call `POST /admin/backups/{backup_id}/verify`.
The CLI's `--verify` flag does the equivalent in one shot (download + re-check SHA-256) and exits
non-zero on failure so cron/systemd records it.

The production Docker image ships **`postgresql-client-16`** (`pg_dump` on `PATH`), so the endpoint
and CLI work in-container out of the box. `pg_dump` refuses to dump a server **newer** than the
client — if you run a Postgres major > 16, bump the client (`postgresql-client-N` in the Dockerfile,
or `PG_DUMP_BIN` on the host).

## Monitoring

- `GET /admin/backups` — the health summary (last successful backup + **age**, ok/failed counts,
  total size) plus recent rows.
- Prometheus (scrape-time gauges): `petabyte_db_backup_last_age_seconds` (**alert when this exceeds
  your RPO**, e.g. > 2× the backup interval; `-1` means *no backup yet*), `petabyte_db_backups_ok`,
  `petabyte_db_backups_failed`, `petabyte_db_backup_bytes`.

## Restore

1. **Pick a backup** — `GET /admin/backups` (or list the bucket). Note the `s3_key`.
2. **Verify integrity first** — `POST /admin/backups/{id}/verify` (checks the stored SHA-256 and
   that it decompresses). Only restore a backup that verifies.
3. **Download + decompress:**
   ```bash
   aws s3 cp "s3://$S3_BUCKET/<key>" backup.sql.gz
   gunzip backup.sql.gz          # -> backup.sql
   ```
4. **Restore into a FRESH database** (never replay over live data — restore into a new DB, verify,
   then cut over):
   ```bash
   # Postgres
   createdb petabyte_restore
   psql "postgresql://user:pass@host:5432/petabyte_restore" -f backup.sql

   # SQLite (dev)
   sqlite3 restored.db < backup.sql
   ```
5. **Sanity-check** the restore (row counts, `scripts/audit_ledger.py` against the restored DB to
   confirm the money ledger still balances), then repoint `DATABASE_URL` and restart the API.

## RPO / RTO + freshness gate

- **RPO (Recovery Point Objective)** — how much data you can afford to lose = **your backup
  interval**. With the hourly cron above, RPO ≈ 1h (you'd lose at most the last hour of writes).
  `BACKUP_RPO_SECONDS` (default **7200s / 2h**, i.e. 2× the hourly cadence) is the *alerting*
  threshold: monitoring fires when the newest successful backup is older than this.
- **RTO (Recovery Time Objective)** — how long recovery takes = download + decompress + `psql`
  replay + cutover. For a small/medium DB this is **minutes**; measure it in your restore drill
  (below) and record the observed time so the number is real, not aspirational.
- **Freshness gate** — `python scripts/backup_database.py --check-fresh` prints
  `backup_freshness` and **exits non-zero when the newest backup exceeds the RPO**. Run it from
  monitoring/cron (independently of the backup itself) so a silently-stalled backup pages you.
  It's the same signal as the `petabyte_db_backup_last_age_seconds` Prometheus gauge.

## Restore drill (tested recovery — automated)

A backup you have never restored is not a backup. The restore is **programmatic and CI-gated**,
not just prose:

```bash
# take a fresh backup, restore it into a THROWAWAY scratch DB, and verify the money ledger still
# balances + row counts match the source. Exits non-zero if recovery is broken.
python scripts/restore_drill.py
# CI (Postgres): point at a dedicated scratch DB so nothing production-shaped is touched
RESTORE_DRILL_TARGET_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/drill \
    python scripts/restore_drill.py
```

The drill (`backup.run_restore_drill`) is **non-destructive** — it never touches the live DB; it
restores into a temp SQLite file or a `<db>_restore_drill` Postgres DB and checks it with the same
`ledger_is_balanced` invariant the money suite uses. It runs on every CI push (SQLite in the fast
suite; **real Postgres** in the "postgres (the one that counts)" job), so a regression that breaks
recovery fails the build. Run it **on a schedule against production backups too**, and record the
observed RTO each time.

## Honest limitations

- **Logical dumps, not PITR.** This gives you point-in-time-of-*backup* recovery, not
  continuous point-in-time recovery (WAL archiving / a managed replica). RPO = your backup interval.
  For tighter RPO, run this alongside managed Postgres PITR — the two are complementary.
- **Not client-side encrypted.** Confidentiality relies on S3 SSE + bucket IAM. The dump is not
  additionally encrypted with the app key, so bucket access = data access. Lock the bucket down.
- **The restore drill proves the mechanism, not your capacity plan.** It verifies a backup restores
  and the ledger balances; it does not load-test recovery at production scale. Measure RTO on a
  production-sized dump before you rely on the number.
