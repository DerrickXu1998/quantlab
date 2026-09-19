# Quickstart: Validating Warehouse-Backed Experiments

This feature has two paths that must both work, and the failure mode to guard against is **fixing one
by breaking the other**. Validate them in this order: the demo path first, because it is existing
behaviour, then the warehouse path.

## 1. The demo path must still work with nothing installed (US2)

The important property is *absence*: no databases, no credentials, no network.

```sh
# from the repository root, with QUANTLAB_DB_URL and QUANTLAB_CH_URL unset
env -u QUANTLAB_DB_URL -u QUANTLAB_CH_URL make up
curl -s localhost:8000/api/v1/health | jq
```

**Expect**: `"dataset": "sqlite"`, `"seeded": true`. Then complete the whole workbench loop in the
browser — browse models, configure, run, inspect, save. Every step behaves as it did before this
feature.

```sh
# The drivers must not be needed at all on this path.
cd backend && python -c "
import sys
for mod in ('psycopg', 'clickhouse_connect'):
    sys.modules[mod] = None      # simulate 'not installed'
from quantlab.api.app import create_app
create_app('/data/quantlab.db')
print('demo path imports cleanly without the warehouse drivers')
"
```

**Expect**: no `ImportError`. A driver import at module scope would break the zero-setup promise, and
this is the cheapest way to catch it.

## 2. Bring up the warehouse

```sh
docker compose up -d postgres clickhouse    # migrate runs automatically
make ingest SYMBOLS="AAPL.US MSFT.US"       # on demand; reaches Stooq/Yahoo
curl -s localhost:8000/api/v1/health | jq
```

**Expect**: `"dataset": "warehouse"`. The workbench should show the active dataset without you
looking at this output.

## 3. Run against real history (US1)

In the browser: pick a model, select real instruments, choose a window inside ingested coverage, run.

**Expect**: signals derived from real bars. Spot-check one — take a reported signal's symbol and date
and confirm it against that instrument's price history.

```sh
# The same run over the API, showing the provenance this feature adds
curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d '{
  "model_name": "sma-crossover",
  "symbols": ["AAPL.US"],
  "start_date": "2021-01-01", "end_date": "2023-12-31"
}' | jq '{dataset, signal_count, coverage, instrument_ids, ingest_run_ids, corporate_actions}'
```

**Expect**: `dataset: "warehouse"`, non-null `instrument_ids` and `ingest_run_ids`, and coverage
populated. Every returned signal's date falls inside the window, and `data_window_end <= date`.

## 4. The checks that matter most

### Re-ingest must be distinguishable (FR-006, SC-006)

```sh
# Run, re-ingest the same window, run again with identical inputs.
A=$(curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d @run.json | jq -r .id)
make ingest SYMBOLS="AAPL.US"
B=$(curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d @run.json | jq -r .id)

diff <(curl -s localhost:8000/api/v1/runs/$A | jq '.ingest_run_ids') \
     <(curl -s localhost:8000/api/v1/runs/$B | jq '.ingest_run_ids')
```

**Expect**: they **differ**. Identical configuration, different data — and the record says so.
Repeating a run *without* re-ingesting must instead reproduce results identically.

### Corporate actions must be reported (FR-008, SC-004)

Run a model over a window containing a known split (e.g. AAPL's 4-for-1 on 2020-08-31).

**Expect**: `corporate_actions` non-empty, naming the split and its ex-date, and the workbench shows
it with the results. Prices are **not** adjusted — the point is that the distortion is visible, not
hidden.

### Experiment output must not reach the curated signals (FR-010, SC-007)

```sh
BEFORE=$(curl -s 'localhost:8000/api/v1/signals?limit=1' | jq .total)
curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d @run.json >/dev/null
AFTER=$(curl -s 'localhost:8000/api/v1/signals?limit=1' | jq .total)
[ "$BEFORE" = "$AFTER" ] && echo "curated signals unaffected ✓" || echo "LEAK ✗"
```

Also confirm directly in Postgres that the catalog's materialised `signals` table is untouched and
that the rows landed in `experiment_signals`.

### Identity must be stable (FR-007, SC-005)

**Expect**: runs record `instrument_ids`, not only symbol strings. Rename an instrument's canonical
symbol in the catalog and confirm an existing saved run still resolves to the same instrument —
identity does not depend on the display string.

## 5. Provenance across datasets (US3)

1. Save a run against the warehouse.
2. Restart with `QUANTLAB_DB_URL`/`QUANTLAB_CH_URL` unset, so the demo is active.
3. Reopen the saved run.

**Expect**: configuration and results fully readable, `re_runnable: false`, clearly marked as not
reproducible under the current configuration. Then compare it against a demo run and confirm the
dataset difference is called out as prominently as a model-version difference.

## 6. Automated checks

```sh
cd backend && pytest        # includes the look-ahead truncation sweep
cd frontend && npm run lint && npm run build && npm test
make check-contract
```

The backend suite must include:

- the `ExperimentStore` contract exercised against **both** adapters
- dataset recorded on every run; warehouse runs carry instrument and ingest provenance
- corporate actions in the window reported
- run output isolated from **both** curated signal tables
- the demo path importing and serving with the warehouse drivers unavailable
- the existing truncation sweep, still passing

## 7. Merge sanity

This feature carries the merge of `worktree-pg-historical-store`.

```sh
git diff --stat main...HEAD -- backend/src/quantlab/api/routes.py
grep -rn "db.connect\|repository\." backend/src/quantlab/api/routes.py || echo "routes go through the seams ✓"
```

**Expect**: no handler reaches past the storage seams to a concrete store. That is what keeps the two
datasets interchangeable — and it is exactly the property the unresolved merge conflict was about.
