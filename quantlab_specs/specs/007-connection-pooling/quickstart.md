# Quickstart: Verifying Reusable Warehouse Connections

Every scenario below maps to a success criterion in `spec.md`. Run them from the
repository root with the stack up (`make up`).

## Prerequisites

```bash
make up                 # postgres, clickhouse, backend, frontend
make check-warehouse    # confirms the API is on the warehouse, not the demo
```

## SC-005 — results are unchanged

The strongest check, and the one to run first: the whole suite must pass without
being modified.

```bash
cd backend && ./.venv/bin/python -m pytest -q          # host: demo path
docker compose run --rm --no-deps backend python -m pytest -q   # container
```

Then confirm an experiment is byte-identical across the change:

```bash
# Before and after, against the same dataset and configuration.
curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' \
  -d '{"model_name":"sma-crossover","symbols":["ZX1.US","ZX2.US"],
       "start_date":"2024-01-01","end_date":"2024-12-31"}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['signal_count'], r['coverage'])"
```

## SC-003 — a repeated request opens no new connections

Watch the connection count at the database while driving identical requests.

```bash
before=$(docker compose exec -T postgres psql -U quantlab -d quantlab -tAc \
  "SELECT count(*) FROM pg_stat_activity WHERE datname='quantlab';")

for i in $(seq 1 50); do curl -s -o /dev/null localhost:8000/api/v1/instruments; done

after=$(docker compose exec -T postgres psql -U quantlab -d quantlab -tAc \
  "SELECT count(*) FROM pg_stat_activity WHERE datname='quantlab';")
echo "before=$before after=$after"
```

**Expected**: `after` is within the pool ceiling of `before`, and does not grow with
the request count. Before this feature it climbs with concurrency.

## SC-001 / SC-002 — concurrency stays inside the budget

```bash
# 100 requests at once, 20 in flight.
seq 1 100 | xargs -P 20 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
  localhost:8000/api/v1/instruments | sort | uniq -c

# Peak connections held, sampled during the run.
docker compose exec -T postgres psql -U quantlab -d quantlab -tAc \
  "SELECT count(*) FROM pg_stat_activity WHERE datname='quantlab' AND state<>'idle';"
```

**Expected**: every line is `200`; the peak never exceeds `QUANTLAB_PG_POOL_MAX`.

## SC-004 — surviving a database restart

```bash
curl -s localhost:8000/api/v1/health
docker compose restart postgres
sleep 5
curl -s localhost:8000/api/v1/instruments | head -c 120   # must succeed
```

**Expected**: succeeds within 30 seconds, with no `docker compose restart backend`.
A dead pooled connection must be discarded, not handed out.

## SC-007 — exhaustion fails fast

```bash
QUANTLAB_PG_POOL_MAX=1 QUANTLAB_POOL_TIMEOUT=2 docker compose up -d backend
seq 1 20 | xargs -P 20 -I{} curl -s -o /dev/null -w '%{http_code} %{time_total}\n' \
  localhost:8000/api/v1/signals
docker compose up -d backend    # restore defaults
```

**Expected**: no request takes materially longer than the 2 s timeout. Failures, if
any, carry a clear error — not a hang.

## SC-006 — the demo path still needs nothing

```bash
docker compose run --rm --no-deps \
  -e QUANTLAB_DB_URL= -e QUANTLAB_CH_URL= backend \
  python -m pytest tests/unit/test_demo_fallback.py -q
```

**Expected**: passes. That suite makes the warehouse drivers unimportable and then
runs a full experiment, so it proves no pool became a prerequisite.

## Deployment check

```bash
BACKEND_URL=https://<your-deployment> make check-warehouse
```
