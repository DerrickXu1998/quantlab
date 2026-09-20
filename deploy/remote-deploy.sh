#!/usr/bin/env bash
# QuantLab -- the part of a deploy that runs ON the VM.
#
# GitHub Actions copies this file, docker-compose.prod.yml, the Caddyfile and
# clickhouse-limits.xml into a staging directory, then runs:
#
#     sudo bash remote-deploy.sh <backend-image> <ingest-image>
#
# Two images, not three: the SPA is served by Vercel, so this VM runs the API
# only. The ingest image is not optional -- the `migrate` service runs from it,
# and the backend will not start until that container has exited successfully.
#
# It lives here rather than inline in the workflow YAML so it can be read,
# linted and run by hand during an incident -- when the last thing you want is
# to reconstruct the deploy from a job log.
#
# The previous image tags are kept in .env.images.prev, so a rollback is:
#
#     cd /opt/quantlab && sudo cp .env.images.prev .env.images && sudo systemctl restart quantlab

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/quantlab}"
STAGE_DIR="${STAGE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
HEALTH_TRIES="${HEALTH_TRIES:-60}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"

BACKEND_IMAGE="${1:?usage: remote-deploy.sh <backend-image> <ingest-image>}"
INGEST_IMAGE="${2:?missing ingest image}"

log() { printf '\n=== %s\n' "$*"; }
fail() { printf 'DEPLOY FAIL: %s\n' "$*" >&2; exit 1; }

compose() {
	docker compose \
		--env-file "$APP_DIR/.env" \
		--env-file "$APP_DIR/.env.images" \
		-f "$APP_DIR/docker-compose.prod.yml" "$@"
}

[ -d "$APP_DIR" ] || fail "$APP_DIR does not exist -- run deploy/bootstrap-vm.sh on this VM first"
[ -f "$APP_DIR/.env" ] || fail "$APP_DIR/.env is missing -- run deploy/bootstrap-vm.sh first"

# --- 1. install the new configuration ----------------------------------------
# Config is copied every deploy, so a change to the compose file or the Caddyfile
# ships exactly like a code change: commit, push, done.
log "installing configuration from $STAGE_DIR"
for f in docker-compose.prod.yml Caddyfile clickhouse-limits.xml; do
	[ -f "$STAGE_DIR/$f" ] || fail "$f missing from the staged deploy"
	install -o root -g root -m 0644 "$STAGE_DIR/$f" "$APP_DIR/$f"
done

# --- 2. record the new image tags --------------------------------------------
log "pinning image tags"
[ -f "$APP_DIR/.env.images" ] && cp "$APP_DIR/.env.images" "$APP_DIR/.env.images.prev"
cat >"$APP_DIR/.env.images" <<IMAGES
# Written by deploy/remote-deploy.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ). Do not edit by hand.
# Rollback: cp .env.images.prev .env.images && systemctl restart quantlab
QUANTLAB_BACKEND_IMAGE=${BACKEND_IMAGE}
QUANTLAB_INGEST_IMAGE=${INGEST_IMAGE}
IMAGES
chmod 0644 "$APP_DIR/.env.images"

# Digest-pinned or tag-pinned, the compose file must at least parse with the
# real environment before anything is pulled or stopped.
compose config >/dev/null || fail "the compose file does not resolve with this environment"

# --- 3. pull ------------------------------------------------------------------
# Pull before touching the running stack: a registry or permission failure then
# leaves the current version serving, rather than a half-stopped one.
log "pulling images"
compose pull --quiet backend || fail "could not pull $BACKEND_IMAGE"
docker pull --quiet "$INGEST_IMAGE" >/dev/null || fail "could not pull $INGEST_IMAGE"

# --- 4. start -----------------------------------------------------------------
# `migrate` is a dependency of `backend` with condition service_completed_successfully,
# so schema changes apply before the new API serves a single request, and a failed
# migration stops the deploy here with the old backend still running.
log "starting the stack"
compose up -d --remove-orphans

# --- 5. wait for health -------------------------------------------------------
log "waiting for the backend healthcheck"
for i in $(seq 1 "$HEALTH_TRIES"); do
	cid="$(compose ps -q backend 2>/dev/null || true)"
	status="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
	[ "$status" = "healthy" ] && { printf 'backend is healthy\n'; break; }
	if [ "$i" -eq "$HEALTH_TRIES" ]; then
		printf 'backend never became healthy. Recent logs:\n' >&2
		compose logs --tail 80 backend migrate >&2 || true
		fail "health timeout after $((HEALTH_TRIES * HEALTH_INTERVAL))s"
	fi
	sleep "$HEALTH_INTERVAL"
done

# --- 6. prove the edge serves it ---------------------------------------------
# Container health only says uvicorn answers on its own port. This is the path a
# browser takes: Caddy -> uvicorn. A broken Caddyfile fails only here.
#
# The probe goes to the configured site address, never http://localhost: with a
# hostname set, Caddy's automatic HTTPS answers every plain-HTTP request with a
# 308 redirect, and a redirect is not a curl -f failure -- the check would pass
# on an empty body while proving nothing. --resolve pins the name to loopback,
# so the real TLS handshake and certificate are exercised from the VM itself,
# without waiting on public DNS propagation.
site="$(sed -n 's/^QUANTLAB_SITE_ADDRESS=//p' "$APP_DIR/.env" | head -1 | tr -d ' "'"'"'')"
[ -n "$site" ] || fail "QUANTLAB_SITE_ADDRESS is empty in $APP_DIR/.env"

if [ "$site" = ":80" ]; then
	edge="http://127.0.0.1"
	edge_args=()
else
	edge="https://$site"
	edge_args=(--resolve "$site:443:127.0.0.1")
fi

log "checking the edge ($edge)"
health=""
for i in $(seq 1 "$HEALTH_TRIES"); do
	if health="$(curl -fsS --max-time 15 "${edge_args[@]}" "$edge/api/v1/health" 2>/dev/null)"; then
		break
	fi
	health=""
	if [ "$i" -eq "$HEALTH_TRIES" ]; then
		compose logs --tail 40 caddy >&2 || true
		fail "Caddy did not proxy $edge/api/v1/health"
	fi
	# On a first deploy Caddy is still obtaining the certificate from Let's
	# Encrypt; issuance takes seconds, occasionally longer, so this retries on
	# the same budget as the backend healthcheck.
	sleep "$HEALTH_INTERVAL"
done
printf 'health: %s\n' "$health"

# The SPA is on Vercel and calls this API cross-origin, so a missing or wrong
# allow-list breaks the whole app while leaving every server-side check green:
# curl has no Origin header, so it never notices. The configured origin comes
# from .env -- the API does not report it -- but the assertion is a real
# preflight against the running service, not a re-read of the file.
log "checking CORS"
origin="$(sed -n 's/^QUANTLAB_CORS_ORIGINS=//p' "$APP_DIR/.env" |
	head -1 | cut -d, -f1 | tr -d ' "'"'"'')"
[ -n "$origin" ] ||
	fail "QUANTLAB_CORS_ORIGINS is empty in $APP_DIR/.env; set it to the Vercel origin or the SPA cannot call this API"
allowed="$(curl -fsS --max-time 15 -o /dev/null -w '%{http_code}' \
	"${edge_args[@]}" \
	-H "Origin: ${origin}" \
	-H 'Access-Control-Request-Method: POST' \
	-H 'Access-Control-Request-Headers: content-type' \
	-X OPTIONS "$edge/api/v1/runs" || true)"
[ "$allowed" = "200" ] ||
	fail "preflight from ${origin} returned ${allowed}, not 200 -- the SPA will be blocked by the browser"
printf 'preflight from %s: ok\n' "$origin"

# The silent-fallback guard. select_backend() drops to the synthetic SQLite demo
# when either warehouse URL is missing, and serves fictitious prices that look
# entirely real. Seeding is not asserted here -- an empty warehouse is a normal
# state for a fresh VM -- but the wrong dataset never is.
case "$health" in
	*'"dataset":"warehouse"'* | *'"dataset": "warehouse"'*) ;;
	*) fail "API is serving the synthetic demo dataset, not the warehouse. Check QUANTLAB_DB_URL / QUANTLAB_CH_URL in $APP_DIR/.env" ;;
esac

log "deploy complete"
compose ps
