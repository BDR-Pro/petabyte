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

# Dependencies first (cached layer). All wheels — no compiler/system libs needed.
COPY lumaris_api/requirements.txt /app/lumaris_api/requirements.txt
RUN pip install --no-cache-dir -r lumaris_api/requirements.txt

# Application code.
COPY . /app

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
