# Quickstart: Validating the Signal Research Workbench

Prerequisites: Docker (for the full stack) or a local Python + Node toolchain.

> Unlike the two preceding features, most of this is **backend-testable end to end**. The model
> catalog, parameter validation, warm-up window, determinism, and run isolation can all be verified
> without a browser — and should be, because they are where the correctness risk lives. The manual
> browser pass covers presentation only.

## 1. Run the stack

```sh
make up                       # seed -> backend -> frontend
# or backend only:
cd backend && uvicorn quantlab.api.app:app --reload
```

## 2. Verify the catalog is genuinely dynamic (FR-001, FR-002, SC-002)

```sh
curl -s localhost:8000/api/v1/models | jq '.items[] | {name, version, lookback_days}'
curl -s localhost:8000/api/v1/models | jq '.items[0].parameters'
```

**Expect**: every registered rule, each with its declared parameters including type, default, and
bounds — not a hardcoded three.

**The real test of SC-002** — register a fourth model and confirm it appears with **no frontend
change and no frontend rebuild**:

```sh
# add a rule via the existing @register_signal_rule decorator, restart the backend
curl -s localhost:8000/api/v1/models | jq '.total'      # incremented
```

Then reload the browser: the new model is selectable and its parameter form renders from its declared
metadata. If this requires touching frontend code, FR-001/FR-002 are not met.

## 3. Verify parameter validation (FR-003)

```sh
# a value outside the declared range must be rejected, naming the parameter
curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d '{
  "model_name": "sma-crossover",
  "parameters": {"fast": -5},
  "symbols": ["ZZTRND"], "start_date": "2024-01-01", "end_date": "2024-06-30"
}' | jq
```

**Expect**: `422`, with the message identifying `fast` specifically. **No run is persisted** — check
`GET /runs` count is unchanged.

## 4. Verify the warm-up window (the correctness trap)

This is the single most important backend check. `sma-crossover` declares `lookback_days: 51`.

```sh
# a window shorter than the model's lookback must be refused, not silently empty
curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d '{
  "model_name": "sma-crossover", "symbols": ["ZZTRND"],
  "start_date": "2024-06-01", "end_date": "2024-06-10"
}' | jq '.detail // .'
```

**Expect**: `422` explaining the window is too short for the model's lookback — *not* a completed run
with zero signals, which would be indistinguishable from "the model found nothing".

```sh
# a valid window: signals must exist early in the window, not only after ~51 days
curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d '{
  "model_name": "sma-crossover", "symbols": ["ZZTRND"],
  "start_date": "2024-03-01", "end_date": "2024-12-31"
}' | jq '{signal_count, coverage, first: (.signals // [] | map(.date) | min)}'
```

**Expect**: `instruments_full_warmup` reports whether history before `start_date` was available, and
signals may appear from the very start of the window — proving warm-up history was loaded rather than
the window being cold-started. Every returned signal's `date` is within `[start_date, end_date]`.

## 5. Verify determinism (FR-011, SC-003)

```sh
A=$(curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d @run.json | jq -r .id)
B=$(curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d @run.json | jq -r .id)
diff <(curl -s localhost:8000/api/v1/runs/$A | jq '.signals') \
     <(curl -s localhost:8000/api/v1/runs/$B | jq '.signals') && echo "identical ✓"
```

**Expect**: byte-identical signal sets from two runs of the same configuration.

## 6. Verify run isolation from seeded signals (the regression guard)

```sh
BEFORE=$(curl -s 'localhost:8000/api/v1/signals?limit=1' | jq .total)
curl -s -X POST localhost:8000/api/v1/runs -H 'content-type: application/json' -d @run.json > /dev/null
AFTER=$(curl -s 'localhost:8000/api/v1/signals?limit=1' | jq .total)
[ "$BEFORE" = "$AFTER" ] && echo "seeded signals unaffected ✓" || echo "LEAK: run output reached /signals ✗"
```

**Expect**: unchanged. Experiment output must never appear in the Signal Viewer's list.

## 7. Verify the zero-signal outcome (FR-008, SC-004)

Run a model over a window or instrument where it genuinely fires nothing.

**Expect**: HTTP `201`, `status: "completed"`, `signal_count: 0`, and coverage populated — a
*successful* run. Anything that looks like an error response is a defect.

## 8. Manual browser pass

1. Open the workbench panels; confirm they arrange, resize, and theme like existing panels (FR-019).
2. Pick a model → the parameter form is built from its declared metadata, with defaults filled.
3. Enter an out-of-range value → the error appears against that field, before any run starts.
4. Select instruments and dates, run → progress is shown and the run can be aborted (FR-006).
5. Inspect results: signals listed, marked on the chart, summary **and coverage shown together**.
6. Force a zero-signal run → reads as a result, never an error.
7. Change one parameter, re-run → both runs remain; compare them and confirm the differing
   configuration values and outcomes are both called out.
8. Compare two runs of different model versions → the version difference is prominent (FR-014).
9. Save, reload the page, reopen the saved experiment → configuration and results intact.
10. Delete a saved experiment → confirmation is requested first.

## 9. Automated checks

```sh
cd backend && pytest                 # includes the look-ahead truncation sweep
cd frontend && npm run lint && npm run build && npm test
make check-contract                  # authored contract vs. the mirrored copy
```

The backend suite must include:

- parameter spec declaration + validation, including rejection cases
- warm-up window: in-window-only reporting, and short-window rejection
- determinism of repeated identical runs
- run output isolation from the seeded `signals` table
- the **existing truncation sweep extended to parameter-overridden runs** — overrides are a new
  execution path the sweep has never covered, and they change lookback behaviour

## 10. Contract sanity checks

```sh
git diff --stat -- backend/contracts/openapi.yaml   # regenerated via `make sync-contract`
grep -rn "RULES = \[" frontend/src || echo "hardcoded rule list removed ✓"
```

- The authored contract now lives at `specs/005-signal-research-workbench/contracts/openapi.yaml`;
  confirm the codegen and drift-check commands point there and that `make check-contract` passes.
- The hardcoded rule list in `SignalFilters.tsx` must be gone — its presence means the catalog is not
  the source of truth.
