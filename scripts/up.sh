#!/usr/bin/env bash
# QuantLab signal viewer demo — bring the full stack up (seed -> backend -> frontend).
#
# Runs the host preflight checks, builds and starts the compose project, then
# blocks until the backend healthcheck passes. Safe to re-run: ports published
# by this project's own running containers are not treated as conflicts.
#
# Usage: scripts/up.sh [extra docker compose up args...]

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose)
# API, UI, Postgres catalog, ClickHouse HTTP, ClickHouse native.
PORTS=(8000 8080 5432 8123 9000)
HEALTH_TRIES="${QUANTLAB_HEALTH_TRIES:-90}"
HEALTH_INTERVAL="${QUANTLAB_HEALTH_INTERVAL:-2}"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- preflight: docker CLI, daemon, compose v2 ---------------------------
command -v docker >/dev/null 2>&1 || \
	fail "'docker' CLI not found. Install Docker Desktop (or Docker Engine) and retry."
docker info >/dev/null 2>&1 || \
	fail "Docker daemon is not reachable. Start Docker Desktop (or the docker service) and retry."
"${COMPOSE[@]}" version >/dev/null 2>&1 || \
	fail "'docker compose' (Compose v2) is not available. Upgrade Docker and retry."

# --- preflight: host ports ------------------------------------------------
# Host ports already published by our own running containers are ours to reuse;
# only a port held by a foreign process is a genuine conflict.
project_ports() {
	local ids
	ids="$("${COMPOSE[@]}" ps -q 2>/dev/null || true)"
	[ -n "$ids" ] || return 0
	# shellcheck disable=SC2086
	docker inspect \
		--format '{{range $p, $conf := .HostConfig.PortBindings}}{{range $conf}}{{.HostPort}} {{end}}{{end}}' \
		$ids 2>/dev/null || true
}

port_in_use() {
	if command -v lsof >/dev/null 2>&1; then
		lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
	elif command -v nc >/dev/null 2>&1; then
		nc -z 127.0.0.1 "$1" >/dev/null 2>&1
	else
		return 1
	fi
}

OURS=" $(project_ports | tr '\n' ' ') "
for port in "${PORTS[@]}"; do
	if port_in_use "$port" && [[ "$OURS" != *" $port "* ]]; then
		fail "host port $port is already in use by another process. Find it with 'lsof -nP -iTCP:$port -sTCP:LISTEN', stop it, and retry."
	fi
done

# --- start ----------------------------------------------------------------
"${COMPOSE[@]}" up --build -d "$@"

# --- wait for the backend healthcheck ------------------------------------
echo "Waiting for backend to become healthy..."
for i in $(seq 1 "$HEALTH_TRIES"); do
	cid="$("${COMPOSE[@]}" ps -q backend 2>/dev/null || true)"
	status="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
	if [ "$status" = "healthy" ]; then
		echo "backend is healthy"
		break
	fi
	if [ "$i" -eq "$HEALTH_TRIES" ]; then
		echo "ERROR: backend did not become healthy in time. Recent backend logs:" >&2
		"${COMPOSE[@]}" logs --tail 50 backend >&2
		exit 1
	fi
	sleep "$HEALTH_INTERVAL"
done

echo "Stack is up. UI: http://localhost:8080  API: http://localhost:8000"

# The warehouse starts empty: ingest reaches the network, so it is never part
# of `up`. Until it runs, the API reports seeded=false and the UI has nothing
# to draw.
if ! "${COMPOSE[@]}" run --rm -T ingest coverage 2>/dev/null | grep -q "total bars"; then
	cat <<'NOTE'

The data warehouse is empty. Load some history:

    make ingest SYMBOLS="AAPL.US MSFT.US HSBA.LON" START=2020-01-01
    make signals

Or seed it with deterministic synthetic bars, which needs no network:

    make seed-warehouse
    make signals

Or run the synthetic demo dataset instead:

    docker compose --profile demo run --rm seed
NOTE
fi
