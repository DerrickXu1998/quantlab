# Phase 1 Data Model: Warehouse-Backed Experiments

One new pair of Postgres tables, provenance fields added to an existing entity, and two protocol
shapes. No change to bars, the catalog, or the materialised signal set.

## Dataset (new — a recorded value, not a table)

Which store a run was computed against.

| Value | Meaning |
|---|---|
| `sqlite` | The synthetic demo dataset. Deterministic, no network, no databases. |
| `warehouse` | Real ingested history: ClickHouse bars over a Postgres catalog. |

Recorded on every run and surfaced in the interface. Two runs with different `dataset` values are
never directly comparable, however identical their configuration — which is why FR-013 requires the
difference to be as prominent as a model-version difference.

## ExperimentRun *(extended)*

The entity from feature 005, gaining provenance. Existing fields — id, name, model name and version,
effective parameters, symbols, window, status, error, created_at, signal_count, the three coverage
counts — are unchanged in meaning.

| New field | Type | Constraint |
|---|---|---|
| `dataset` | enum | Required. `sqlite` \| `warehouse`. |
| `instrument_ids` | list of integer \| null | Required when `dataset = warehouse`; null on the demo. The surrogate identities actually run against. Recorded because the canonical symbol is unique but editable, while `instrument_id` is the stable key the bar store joins on. |
| `ingest_run_ids` | list of integer \| null | Required when `dataset = warehouse` and the run read any bars; null on the demo. The ingest runs behind the bars read. **This is what makes a re-ingest of the same window distinguishable from the original run** (FR-006). |
| `corporate_actions` | list of Corporate Action Notice | Possibly empty. Actions overlapping the window for the selected instruments. Empty on the demo, which has none. |

**Validation rules**:

- `dataset` is required on every run; a run with no recorded dataset is not valid (SC-003).
- `instrument_ids` and `ingest_run_ids` are populated together with `dataset = warehouse`; a
  warehouse run that read bars but recorded no ingest provenance is a defect, not an edge case.
- A run remains readable when its `dataset` is not the active one, and is then marked not re-runnable
  (FR-012) — readability never depends on the current configuration.

## Corporate Action Notice (new — reported, not stored by this feature)

What the runner found in `corporate_actions` overlapping the run window. Reported so a
split-distorted result is recognisable; **prices are not adjusted** (see `research.md`).

| Field | Type | Notes |
|---|---|---|
| `instrument_id` | integer | Which instrument is affected. |
| `symbol` | string | Canonical symbol, for display. |
| `ex_date` | date | Falls within the run's `[start_date, end_date]`. |
| `action_type` | enum | `split` \| `dividend`, matching the catalog's CHECK constraint. |
| `split_ratio` | number \| null | Present for splits. |
| `dividend` | number \| null | Present for dividends. |

A split inside the window is the case that matters most: unadjusted bars make it look like a price
move. A dividend is reported for completeness.

## ExperimentSignal *(warehouse store — new table, same meaning)*

Mirrors the SQLite table from feature 005, keyed by surrogate identity rather than symbol text.

| Field | Type | Constraint |
|---|---|---|
| `run_id` | reference | Required, references the run. Deleting a run deletes its signals. |
| `instrument_id` | integer | Required, references `instruments`. |
| `date` | date | Required. Must fall within the run's window — warm-up signals are computed but not reported. |
| `direction` | enum | Required. `bullish` \| `bearish`. |
| `trigger_values` | JSON object | Required. |
| `data_window_end` | date | Required. **Must be `<= date`** — the same point-in-time CHECK the catalog's own `signals` table carries (Constitution VII). |

**Deliberately separate from the catalog's materialised `signals` table**, which is a rebuildable
cache of registry output and would accept this data cleanly before surfacing it in the Signal Viewer.

## StorageBackend *(protocol — extended)*

What a route or the runner may ask of the active dataset.

| Method | Status | Purpose |
|---|---|---|
| `health`, `instrument_exists`, `list_instruments`, `get_prices`, `list_signals` | existing | Unchanged. |
| `load_bars_for(symbols, start, end)` | **new** | Bars for several instruments across one window. The runner passes the *warm-up* start, not the researcher's start. |
| `earliest_bar_dates(symbols)` | **new** | First available bar per instrument, for warm-up coverage reporting. |
| `corporate_actions(symbols, start, end)` | **new** | Actions overlapping the window. Returns empty on the demo. |

Both adapters implement all of it. `name` continues to identify the dataset.

## ExperimentStore *(protocol — new)*

Where experiment runs live. Separate from `StorageBackend` because on the warehouse these are
different database systems, and because a dataset adapter should not own user artefacts.

| Method | Purpose |
|---|---|
| `save_run(result)` | Persist a run with its provenance and produced signals. |
| `get_run(run_id)` | One run with its signals, or nothing. |
| `list_runs(saved_only)` | Runs newest-first, optionally only named ones. |
| `set_run_name(run_id, name)` | Save a run as a named experiment. |
| `delete_run(run_id)` | Remove a run **and its signals together**. |

Two adapters: SQLite (the existing tables, keyed by symbol) and Postgres (the new tables, keyed by
`instrument_id`). Both satisfy the same contract, which is what lets one test suite cover both.

## Existing entities (unchanged)

- **Price Bar**, **Instrument**, **Symbol Map**, **Universe Snapshot**, **Ingest Run**,
  **Corporate Action** *(catalog)* — read, never written by this feature.
- **Model**, **Parameter Definition**, **Run Result**, **Saved Experiment** — unchanged in meaning;
  Run Result carries the new provenance above.
- The catalog's materialised **signals** table and the demo's seeded **signals** table — untouched.
