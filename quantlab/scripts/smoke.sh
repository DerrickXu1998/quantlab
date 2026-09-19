#!/usr/bin/env bash
# QuantLab signal viewer demo — end-to-end smoke check.
# Asserts: backend healthy, DB seeded with signals, every starter rule fired,
# and the frontend serves HTTP 200. Exits non-zero on the first failure.

set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:8080}"
MAX_WAIT="${SMOKE_MAX_WAIT:-120}"
RULES="sma-crossover rsi-threshold breakout-20d"

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
pass() { echo "SMOKE PASS: $*"; }

command -v docker >/dev/null 2>&1 || \
	fail "'docker' CLI not found. Install Docker and run 'make up' first."
docker info >/dev/null 2>&1 || \
	fail "Docker daemon is not reachable. Start Docker and run 'make up' first."
command -v curl >/dev/null 2>&1 || \
	fail "'curl' is required for the smoke check."

# JSON parsing: prefer python3, fall back to jq, fail clearly if neither.
if command -v python3 >/dev/null 2>&1; then
	JSON_TOOL=python3
elif command -v jq >/dev/null 2>&1; then
	JSON_TOOL=jq
else
	fail "neither 'python3' nor 'jq' found on PATH; install one to parse JSON responses"
fi

json_field() { # json_field <key>  (JSON document on stdin)
	if [ "$JSON_TOOL" = "python3" ]; then
		python3 -c "import json, sys; print(json.load(sys.stdin)[sys.argv[1]])" "$1"
	else
		jq -r --arg k "$1" '.[$k]'
	fi
}

echo "Waiting for backend at ${BACKEND_URL} (up to ${MAX_WAIT}s)..."
elapsed=0
until curl -fsS "${BACKEND_URL}/api/v1/health" >/dev/null 2>&1; do
	sleep 2
	elapsed=$((elapsed + 2))
	if [ "$elapsed" -ge "$MAX_WAIT" ]; then
		fail "backend did not respond at ${BACKEND_URL}/api/v1/health within ${MAX_WAIT}s (is the stack up? try 'make up' / 'make logs')"
	fi
done

health=$(curl -fsS "${BACKEND_URL}/api/v1/health") || fail "GET /api/v1/health failed"

status=$(printf '%s' "$health" | json_field status)
[ "$status" = "ok" ] || fail "GET /api/v1/health returned status='$status', expected 'ok'"
pass "backend health status is 'ok'"

seeded=$(printf '%s' "$health" | json_field seeded | tr '[:upper:]' '[:lower:]')
[ "$seeded" = "true" ] || fail "health reports seeded=$seeded, expected true (run 'make seed' or 'make up')"
pass "database is seeded"

signal_count=$(printf '%s' "$health" | json_field signal_count)
[ "$signal_count" -ge 1 ] 2>/dev/null || fail "health reports signal_count=$signal_count, expected >= 1"
pass "signal_count = $signal_count (>= 1)"

for rule in $RULES; do
	body=$(curl -fsS "${BACKEND_URL}/api/v1/signals?signal_type=${rule}&limit=1") || \
		fail "GET /api/v1/signals?signal_type=${rule} failed"
	total=$(printf '%s' "$body" | json_field total)
	[ "$total" -ge 1 ] 2>/dev/null || \
		fail "rule '${rule}' has ${total} signals, expected >= 1 (every starter rule must fire on the synthetic dataset)"
	pass "rule '${rule}' fired ($total signal(s))"
done

code=$(curl -s -o /dev/null -w '%{http_code}' "${FRONTEND_URL}/")
[ "$code" = "200" ] || fail "frontend at ${FRONTEND_URL} returned HTTP $code, expected 200"
pass "frontend serves HTTP 200 at ${FRONTEND_URL}"

echo "SMOKE OK: all checks passed."
