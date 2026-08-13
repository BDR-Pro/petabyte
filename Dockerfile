# Petabyte API — production image.
# Canonical entrypoint is `lumaris_api.main:app` imported from the repo root (the same path
# CI proves works via scripts/repo_root_import_test.py). Served by gunicorn + uvicorn workers
# using the repo's own gunicorn config (worker recycling, timeouts).
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# pg_dump for platform database backups (backup.py / scripts/backup_database.py). Pinned to 16
# to match modern managed Postgres — pg_dump refuses to dump a server NEWER than the client, so
# Debian's default (15) would fail against a PG16 server. Installed from the PostgreSQL APT repo.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*

# Dependencies first (cached layer). All wheels — no compiler/system libs needed.
COPY lumaris_api/requirements.txt /app/lumaris_api/requirements.txt
RUN pip install --no-cache-dir -r lumaris_api/requirements.txt

# Application code.
COPY . /app

# Bundle the agent code so GET /agent.tar.gz works in the image (the node installer fetches this
# instead of cloning GitHub, so onboarding keeps working even when the repo is private). Deploy
# scripts build the same artifact on a host; this makes the Docker image self-sufficient too.
RUN tar -czf /app/lumaris_api/installers/agent.tar.gz -C /app lumaris_agent

# Run as an unprivileged user — never root inside the container.
RUN useradd --create-home --uid 10001 petabyte && chown -R petabyte:petabyte /app
USER petabyte

# Bind to all interfaces INSIDE the container (front it with nginx/an ingress in prod).
ENV BIND=0.0.0.0:8000 \
    WEB_CONCURRENCY=2 \
    PAYMENTS_MODE=sandbox \
    LOG_LEVEL=info

EXPOSE 8000

# Liveness via the app's own health endpoint (no extra tools installed).
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"]

# gunicorn reads BIND/WEB_CONCURRENCY/LOG_LEVEL from the environment.
CMD ["gunicorn", "-c", "lumaris_api/deploy/gunicorn_conf.py", "lumaris_api.main:app"]
