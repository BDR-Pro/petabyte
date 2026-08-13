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

Run the CLI on the API host, where `DATABASE_URL` + `S3_*` are already in the environment:

```cron
# /etc/cron.d/petabyte-db-backup  — hourly
0 * * * *  petabyte  . /etc/lumaris/lumaris.env && \
    /opt/petabyte/venv/bin/python /opt/petabyte/scripts/backup_database.py --verify \
    >> /var/log/petabyte-backup.log 2>&1
```

`--verify` re-downloads the object and re-checks its SHA-256 after upload. The CLI exits non-zero on
failure so cron/systemd records it. You can also trigger one on demand: `POST /admin/backups/run`.

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

## Honest limitations

- **Logical dumps, not PITR.** This gives you point-in-time-of-*backup* recovery, not
  continuous point-in-time recovery (WAL archiving / a managed replica). RPO = your backup interval.
  For tighter RPO, run this alongside managed Postgres PITR — the two are complementary.
- **Not client-side encrypted.** Confidentiality relies on S3 SSE + bucket IAM. The dump is not
  additionally encrypted with the app key, so bucket access = data access. Lock the bucket down.
- **Restore is a documented manual procedure**, not an automated one-click failover. Practise it.
