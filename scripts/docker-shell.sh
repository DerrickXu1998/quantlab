#!/usr/bin/env bash
# QuantLab signal viewer demo — open an interactive shell inside a container.
#
# Brings the stack up first if it is not already running, then execs a shell in
# the target service (bash where the image has it, sh otherwise).
#
# Usage: scripts/docker-shell.sh [service] [command...]
#   scripts/docker-shell.sh                  # bash in the backend container
#   scripts/docker-shell.sh frontend         # sh in the nginx container
#   scripts/docker-shell.sh backend pytest -q  # run one command instead

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose)
SERVICE="${1:-backend}"
[ $# -gt 0 ] && shift

command -v docker >/dev/null 2>&1 || {
	echo "ERROR: 'docker' CLI not found. Install Docker Desktop (or Docker Engine) and retry." >&2; exit 1; }
docker info >/dev/null 2>&1 || {
	echo "ERROR: Docker daemon is not reachable. Start Docker Desktop (or the docker service) and retry." >&2; exit 1; }

# Start the stack if this service has no running container yet.
if [ -z "$("${COMPOSE[@]}" ps -q "$SERVICE" 2>/dev/null || true)" ]; then
	echo "Service '$SERVICE' is not running; starting the stack first..."
	bash scripts/up.sh
fi

cid="$("${COMPOSE[@]}" ps -q "$SERVICE" 2>/dev/null || true)"
[ -n "$cid" ] || { echo "ERROR: no container for service '$SERVICE'." >&2; exit 1; }

# Pick a shell the image actually ships (nginx:alpine has no bash).
SHELL_BIN=bash
docker exec "$cid" sh -c 'command -v bash >/dev/null 2>&1' || SHELL_BIN='sh'

# Without a TTY (CI, pipes) `compose exec` must be told not to allocate one.
TTY_FLAG=()
[ -t 0 ] || TTY_FLAG=(-T)

if [ $# -gt 0 ]; then
	exec "${COMPOSE[@]}" exec "${TTY_FLAG[@]}" "$SERVICE" "$SHELL_BIN" -lc "$*"
fi

echo "Opening $SHELL_BIN in '$SERVICE' (exit or Ctrl-D to leave)."
exec "${COMPOSE[@]}" exec "${TTY_FLAG[@]}" "$SERVICE" "$SHELL_BIN"
