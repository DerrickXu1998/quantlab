# Quickstart: Dockerized Signal Viewer on Synthetic Data

**Feature**: `002-signal-viewer-demo` | **Date**: 2026-09-19

Runnable validation scenarios proving the feature end-to-end. Each scenario maps to a
Success Criterion in [spec.md](spec.md). API shapes referenced below are defined in
[contracts/openapi.yaml](contracts/openapi.yaml); storage details in
[data-model.md](data-model.md).

## Prerequisites

- Docker (with Compose v2) and GNU Make on the host. Nothing else.
- A fresh clone of the repository on branch `002-signal-viewer-demo`.

## Scenario 1 — Clean-machine setup (SC-001)

```bash
git clone <repo> && cd quantlab
make up          # builds images, runs the one-shot seed, starts backend + frontend
make smoke       # waits for health and prints the signal count
```

Expected: in under 10 minutes, `make smoke` reports backend healthy, `seeded: true`, and
a signal count > 0. Open `http://localhost:8080` — the signal list renders with the total
count visible. Teardown with `make down` stops and removes all containers; a later
`make up` reseeds from clean state.

Fail-fast checks: if Docker is not running or port 8080/8000 is taken, `make up` exits
non-zero with a message naming the problem (no partial stack).

## Scenario 2 — Determinism across runs (SC-002, FR-005)

```bash
make up && make dump-hash > /tmp/hash-a.txt
make down && make up && make dump-hash > /tmp/hash-b.txt
diff /tmp/hash-a.txt /tmp/hash-b.txt
```

Expected: `diff` produces no output — the ordered database dump is identical across two
independent setups. The same comparison runs as an automated test
(`backend/tests/unit/test_seed.py`).

## Scenario 3 — Dataset coverage and rule firing (SC-003, FR-004, FR-007)

```bash
curl -s localhost:8000/api/v1/instruments | jq '.total'          # >= 10
curl -s "localhost:8000/api/v1/instruments/ZZTRND/prices" | jq '.total'   # >= 750 bars
curl -s "localhost:8000/api/v1/signals?signal_type=sma-crossover" | jq '.total'   # >= 1
curl -s "localhost:8000/api/v1/signals?signal_type=rsi-threshold" | jq '.total'   # >= 1
curl -s "localhost:8000/api/v1/signals?signal_type=breakout-20d"  | jq '.total'   # >= 1
```

Expected: at least 10 fictitious instruments, each with ≥ 3 years of weekday bars, and
every starter rule has fired at least once. All symbols are recognizably fake (FR-006).

## Scenario 4 — UI/backend count consistency (SC-004, FR-010, FR-011)

1. Open `http://localhost:8080`; note the displayed total signal count.
2. Compare with `curl -s localhost:8000/api/v1/signals | jq '.total'` — must match exactly.
3. In the UI, filter by one instrument and a date range; note the filtered count.
4. Compare with the equivalent query:
   `curl -s "localhost:8000/api/v1/signals?instrument=ZZTRND&start_date=…&end_date=…" | jq '.total'`.

Expected: counts match in both cases; sorting by date in the UI reorders without changing
the count; a filter matching nothing shows the explicit empty state (not a blank view).

## Scenario 5 — Signal re-derivation and no look-ahead (SC-005, FR-008)

```bash
make test        # runs backend unit + contract + look-ahead suites inside containers
```

Expected: all suites pass, including:

- `test_signal_rederivation` — recomputing every rule from stored bars reproduces the
  stored signal set exactly (zero discrepancies on the full sweep).
- `backend/tests/lookahead/` — every rule recomputed on truncated history emits no signal
  whose `data_window_end` exceeds the truncation point.
- Contract tests — every API response validates against `contracts/openapi.yaml`.

## Scenario 6 — Signal context view (FR-012) and UI states (FR-013)

1. Select any signal in the list → the instrument's price chart appears with the signal
   marked at its date.
2. Stop the backend (`docker compose stop backend`) and reload the UI → a distinct error
   state is shown, not an empty "no signals" list.
3. `docker compose start backend` → the list recovers.
