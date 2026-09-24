#!/usr/bin/env bash
# QuantLab — local development: Docker backend + hot-reloading frontend.
#
# Brings the stack (backend, Postgres, ClickHouse, :8080 frontend) up through
# scripts/up.sh, so it gets the same preflight checks and healthcheck wait as
# `make up`, and is rebuilt from the current source every time. Then runs the
# Vite dev server (usually :5173) in the foreground: edits under frontend/src
# show up in the browser without a rebuild, and /api is proxied to :8000.
#
# Ctrl-C stops the frontend only. The backend keeps running; `make down`
# stops it.
#
# Usage: scripts/dev.sh
#   AUTH_BYPASS=1 scripts/dev.sh   # no login: backend auth off + dev server gate skipped

set -euo pipefail

cd "$(dirname "$0")/.."

fail() { echo "ERROR: $*" >&2; exit 1; }

command -v npm >/dev/null 2>&1 || \
	fail "'npm' not found. Install Node.js 20+ and retry (or use 'make up' for the all-Docker stack)."

# --- auth -----------------------------------------------------------------
# The bypass has to reach the backend too: a frontend that skips the login
# screen in front of an API that still wants a token just trades the login
# form for a page of 401s. With auth off, /health says so and the UI opens
# without a login screen; the Vite flag covers pointing at an API that has auth on.
if [ "${AUTH_BYPASS:-}" = "1" ] || [ "${AUTH_BYPASS:-}" = "true" ]; then
	export QUANTLAB_AUTH_REQUIRED=false VITE_AUTH_BYPASS=true
	echo "Login bypassed: backend auth off, dev server skips the login screen."
fi

# --- backend (and the :8080 frontend image) -------------------------------
# The whole stack, not just the backend: a frontend container left on an old
# image keeps serving old UI on :8080, and that is easy to mistake for a fix
# that did not work.
bash scripts/up.sh

# --- frontend dependencies ------------------------------------------------
# Reinstall when node_modules is missing or older than the lockfile, so a
# pulled branch with new packages does not fail with a module-not-found.
if [ ! -f frontend/node_modules/.package-lock.json ] || \
	[ frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]; then
	echo "Installing frontend dependencies..."
	(cd frontend && npm ci)
fi

# --- frontend (hot reload) -----------------------------------------------
# Vite picks the next free port if 5173 is taken, so the URL it prints below is
# the one to open.
echo "Backend: http://localhost:8000   Frontend: the Local URL Vite prints below   (Ctrl-C stops the frontend)"
cd frontend
exec npm run dev
