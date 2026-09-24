# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QUANTLAB_DB=/data/quantlab.db \
    QUANTLAB_DB_PATH=/data/quantlab.db

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Test/CI image: the runtime plus the suite and its dev extras, so the same
# build context can run pytest from /app (`make test`). The dev compose file
# builds this target explicitly; it is never deployed.
FROM base AS dev
COPY tests ./tests
COPY contracts ./contracts
RUN pip install --no-cache-dir ".[dev]"

# Serving image: runtime dependencies only, and the process runs as an
# unprivileged user. This is the default target, so `docker build .` and the
# deploy workflow get the hardened image. CI builds with `--target dev` to run
# pytest instead.
FROM base
RUN useradd --system --uid 10001 quantlab \
    && mkdir -p /data \
    && chown quantlab:quantlab /data
USER quantlab

VOLUME ["/data"]

EXPOSE 8000

# Shell form, deliberately: a container platform (Cloud Run, Fly, Render)
# injects $PORT and health-checks that port, and exec-form CMD does not expand
# variables -- uvicorn would receive the literal string "${PORT}". The default
# keeps docker-compose, which sets no $PORT, working unchanged.
CMD uvicorn quantlab.api.app:app --host 0.0.0.0 --port ${PORT:-8000}
