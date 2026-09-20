#!/usr/bin/env bash
# Assert the API is actually serving the warehouse, not the synthetic fallback.
#
# Why this exists: select_backend() falls back to the SQLite demo dataset when
# either QUANTLAB_DB_URL or QUANTLAB_CH_URL is missing, and it does so silently.
# A typo in one variable does not raise -- it serves fictitious instruments and
# prices that look entirely real. This is the check that makes that loud.
#
# It also catches the split-brain case: a remote bar store paired with a local
# catalog resolves instruments fine and then returns no prices for any of them.
#
# Usage:  scripts/check-warehouse.sh            # against localhost:8000
#         BACKEND_URL=https://api.example.com scripts/check-warehouse.sh
#         EXPECT_DATASET=sqlite scripts/check-warehouse.sh   # demo deploys

set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
EXPECT_DATASET="${EXPECT_DATASET:-warehouse}"
MIN_INSTRUMENTS="${MIN_INSTRUMENTS:-1}"

fail() { echo "WAREHOUSE FAIL: $*" >&2; exit 1; }
pass() { echo "WAREHOUSE PASS: $*"; }

command -v curl >/dev/null 2>&1 || fail "'curl' is required."
command -v python3 >/dev/null 2>&1 || fail "'python3' is required."

api() { curl -fsS --max-time 20 "$BACKEND_URL/api/v1$1" 2>/dev/null || true; }
field() { python3 -c "import json,sys;d=json.load(sys.stdin);print(d$1)" 2>/dev/null || true; }

# --- 1. reachable --------------------------------------------------------
HEALTH="$(api /health)"
[ -n "$HEALTH" ] || fail "no response from $BACKEND_URL/api/v1/health"

# --- 2. the right dataset is answering -----------------------------------
DATASET="$(printf '%s' "$HEALTH" | field "['dataset']")"
[ -n "$DATASET" ] || fail "health returned no 'dataset' field: $HEALTH"
[ "$DATASET" = "$EXPECT_DATASET" ] || fail \
	"serving '$DATASET', expected '$EXPECT_DATASET'. If this is a deploy, one of
       QUANTLAB_DB_URL / QUANTLAB_CH_URL is unset or wrong -- the API fell back
       to the synthetic demo and is serving fictitious data."
pass "dataset is '$DATASET'"

# --- 3. seeded -----------------------------------------------------------
SEEDED="$(printf '%s' "$HEALTH" | field "['seeded']")"
[ "$SEEDED" = "True" ] || fail "dataset '$DATASET' reports seeded=$SEEDED"
pass "dataset reports seeded"

# --- 4. the catalog has instruments --------------------------------------
INSTRUMENTS="$(api /instruments)"
COUNT="$(printf '%s' "$INSTRUMENTS" | field "['total']")"
[ -n "$COUNT" ] || fail "could not read instruments: $INSTRUMENTS"
[ "$COUNT" -ge "$MIN_INSTRUMENTS" ] || fail \
	"catalog holds $COUNT instruments, expected at least $MIN_INSTRUMENTS"
pass "catalog holds $COUNT instruments"

# --- 5. bars actually come back ------------------------------------------
# The split-brain check. A remote bar store behind a local catalog passes
# every test above and fails here, which is the whole point.
SYMBOL="$(printf '%s' "$INSTRUMENTS" | field "['items'][0]['symbol']")"
[ -n "$SYMBOL" ] || fail "catalog reported $COUNT instruments but listed none"

BARS="$(api "/instruments/$SYMBOL/prices")"
BAR_COUNT="$(printf '%s' "$BARS" | field "['total']")"
[ -n "$BAR_COUNT" ] || fail "could not read prices for $SYMBOL: $BARS"
[ "$BAR_COUNT" -gt 0 ] || fail \
	"$SYMBOL resolves in the catalog but has zero bars. The bar store and the
       catalog are pointing at different places -- check that QUANTLAB_CH_URL
       and QUANTLAB_DB_URL name the same environment."
pass "$SYMBOL returned $BAR_COUNT bars"

echo "WAREHOUSE OK: $BACKEND_URL is serving '$DATASET' with real bars."
