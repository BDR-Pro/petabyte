import os

bind = os.getenv("BIND", "127.0.0.1:8000")
# Default to 2 workers — safe on small (512MB-1GB) droplets. Raise WEB_CONCURRENCY
# on bigger boxes (a good rule is 2*vCPU+1 when you have >=1GB RAM per 2 workers).
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1000          # recycle workers to bound memory
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
