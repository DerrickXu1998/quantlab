# syntax=docker/dockerfile:1
#
# live-ingest: the IBKR collector for the Market tab's live view (roadmap 4a).
# Reads leases from Postgres, streams prices from IB Gateway to Kafka and
# today's minutes to ClickHouse. No credentials of its own: it talks to the
# ib-gateway container, which holds the IBKR login.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests

RUN pip install --no-cache-dir ".[dev]" \
    && useradd --create-home --uid 10001 collector
USER collector

ENTRYPOINT ["quantlab-live-ingest"]
