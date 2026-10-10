# CatSight API — Cloud Run container.
#
# Python 3.12 to match the local venv. Not 3.13+: `google-adk`
# 2.11.0 is verified against 3.12, and a runtime the tests never ran on is a
# deployment-only variable.

FROM python:3.12-slim AS base

# PYTHONUNBUFFERED so logs reach Cloud Logging as they happen rather than when
# a buffer flushes - a crash with a swallowed traceback is very hard to debug.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements first, as their own layer: application code changes on every
# deploy and the dependency install does not, so this keeps rebuilds fast.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY catsight_agent/ ./catsight_agent/
COPY ingest/ ./ingest/
COPY app/ ./app/

# The replay events, the vulnerability parameters, the synthetic portfolio's
# wordings and the answer key. Small, and the service cannot answer without
# them: an analysis reads data/events/*.json on every request.
COPY data/ ./data/

# The built SPA, served by this same service so there is one deploy and one
# origin - see `_mount_frontend`. Built with `npm --prefix frontend run build`
# BEFORE the image is built; if the directory is absent the API still serves
# and /healthz reports `frontend: false`.
COPY static/ ./static/

# Run as a non-root user. Cloud Run does not require it, but a container that
# only ever reads its own files has no reason to be root.
RUN useradd --create-home --uid 1000 catsight && chown -R catsight:catsight /app
USER catsight

# Cloud Run injects PORT and may change it; honour it rather than hardcoding
# 8080, or the container passes health checks locally and fails in production.
ENV PORT=8080
EXPOSE 8080

# One worker. Analyses are I/O-bound on model calls, uvicorn handles them
# concurrently within the process, and Cloud Run scales by adding instances -
# so extra workers would multiply memory for no throughput.
#
# --proxy-headers: on Cloud Run every request arrives through Google's front
# end, so without reading X-Forwarded-For every visitor shares one address and
# the per-IP rate limit (FR-GUARD) becomes a global one. Trusting all forwarders
# is safe here because only that front end can reach the container.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 65 --proxy-headers --forwarded-allow-ips="*"
