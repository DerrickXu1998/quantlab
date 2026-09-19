# Phase 0 Research: Warehouse-Backed Experiments

Findings below come from reading both branches' schemas and source, not from recall. One of them
**corrects a requirement in this feature's own spec**, which is recorded here rather than quietly
implemented around.

## Correction: the ticker-reuse requirement (FR-007) is overstated

**What the spec says.** FR-007 requires resolving the researcher's chosen symbols to instruments *as
of the run window*, on the grounds that vendor tickers get reused and a long window would otherwise
splice two companies into one series.

**What the schema actually does.** There are two different kinds of symbol in the catalog:

- `instruments.symbol` — the **canonical quantlab id** (`AAPL.US`, `HSBA.LON`), `NOT NULL UNIQUE`,
  and the identity the API already exposes. `warehouse.get_prices` resolves through this column.
- `symbol_map.vendor_symbol` — **what a vendor calls it** (`aapl.us` for Stooq), bound to an
  instrument over a `DATERANGE`, with a GiST exclusion constraint making it impossible for one vendor
  symbol to point at two instruments on the same day.

The ticker-reuse hazard is therefore real but it lives at the **ingest boundary**, where vendor
tickers are translated, and it is already enforced by the database. The workbench never sees vendor
tickers: it selects canonical symbols, which are unique and stable.

**Decision**: do not build as-of vendor-symbol resolution. Instead, **record `instrument_id` on
warehouse runs** rather than only the symbol string, so a run's provenance survives a canonical
symbol being corrected later. The spirit of FR-007 — a run must never conflate two instruments — is
satisfied by keying on the surrogate id, which is the stable identity the schema was designed around.

**Why this is worth stating plainly**: implementing FR-007 literally would have added a date-ranged
vendor-symbol lookup to the read path that duplicates a constraint the database already enforces, to
solve a problem the workbench does not have. The requirement should be read as "identity must be
stable", and it is satisfiable more simply than the spec assumed.

## Decision: two seams, not one extended protocol

**What exists.** `StorageBackend` is a five-method Protocol — `health`, `instrument_exists`,
`list_instruments`, `get_prices`, `list_signals` — with `SqliteBackend` and `WarehouseBackend`
implementations, selected once at startup by `select_backend()`. Routes "talk to whichever backend is
bound to `app.state.backend` and never branch on which one it is."

**What the workbench needs beyond it.** Windowed multi-instrument bar loading, per-instrument
earliest-bar dates (for warm-up coverage), and five run-persistence operations.

**Decision**: extend `StorageBackend` with the two *read* methods, and introduce a separate
`ExperimentStore` protocol for persistence, with SQLite and Postgres adapters.

**Rationale.** The two questions vary independently. "Which dataset am I reading?" is about market
data; "where do my experiments live?" is about user artefacts. On the warehouse they are different
systems entirely — bars in ClickHouse, runs in Postgres — so a single protocol would bundle a
ClickHouse concern and a Postgres concern behind one name. Separating them also makes experiment
persistence testable without any bar store at all.

**Alternatives considered**: one seven-method `StorageBackend` (rejected — see Complexity Tracking in
`plan.md`); leaving experiment persistence on SQLite even when the warehouse is active (rejected —
runs would then be invisible to anything reading the catalog, and the demo database becomes a
required dependency of the warehouse path, which defeats the point of the fallback).

## Decision: how a run proves which data it used

FR-006 requires distinguishing a run from a later re-ingest of the same window — a case where every
input the researcher chose is identical but the underlying data changed.

**The schema already carries the answer.** Every row in `price_bars` has a `run_id`, a foreign key in
spirit to Postgres `ingest_runs`, and it doubles as the `ReplacingMergeTree(run_id)` version: a
re-ingest writes rows with a higher `run_id` that supersede the earlier copies.

**Decision**: a warehouse run records the set (or maximum) of `run_id` values across the bars it
actually read. Two runs with identical configuration but different ingest provenance are then
visibly different, and a result can be traced to the exact ingest that produced its inputs.

**Alternatives considered**: hashing the bars read (rejected — expensive on wide scans and opaque
when it differs); recording a wall-clock timestamp only (rejected — says when the run happened, not
what it read, and Constitution VI forbids wall-clock inside computation anyway); assuming ingested
data is immutable (rejected — the store is explicitly designed for re-ingest).

## Decision: report corporate actions, do not adjust

**The hazard.** Bars are stored **unadjusted** by deliberate design, and `adj_close` is kept only as
"the vendor's opinion on the day it was fetched", explicitly not authoritative because "adj_close
today differs from adj_close as of 2019". A model run across an unadjusted split sees a price
discontinuity that is an artefact.

**Decision**: the runner queries `corporate_actions` for the selected instruments over the run window
and reports what it finds alongside coverage. It does **not** adjust prices.

**Rationale.** `corporate_actions` exists precisely so a point-in-time adjustment factor can be
rebuilt for any as-of date — which is a real feature with its own correctness requirements (which
as-of date? applied to which fields? how does it interact with the warm-up window?). Silently picking
an adjustment policy inside this feature would bury a research-significant decision in a plumbing
change. Reporting makes a distorted result *recognisable* now, and leaves the adjustment feature
properly specifiable later.

**Alternatives considered**: using vendor `adj_close` (rejected — non-authoritative by design, and
using it would silently poison backtests, which is the exact failure the schema comment warns about);
refusing to run over a window containing an action (rejected — far too strict; splits are common and
plenty of research is unaffected).

## Decision: experiment output stays out of the materialised signal set

The warehouse has its own `signals` table — described in its migration as "a cache that can be
dropped and rebuilt", keyed `UNIQUE (instrument_id, rule_id, date)` with `rule_id` pointing at
`signal_rules(rule_name, rule_version, parameters)`.

**This is the same trap feature 005 found on SQLite, on a different store.** Experiment output would
insert into it cleanly — parameters are part of the key — and would then surface in the Signal
Viewer, mixing exploratory runs into curated output with nothing to indicate it.

**Decision**: a new Postgres migration adds `experiment_runs` and `experiment_signals`, mirroring the
SQLite tables, keyed by `instrument_id` with the same `data_window_end <= date` point-in-time CHECK.
The materialised `signals` table is not written to by this feature.

## Decision: the demo path must not acquire a database dependency

`select_backend()` already falls back to SQLite when the warehouse is not configured, and the spec
makes preserving that a first-class story (US2). The risk in this feature is acquiring the dependency
*accidentally* — e.g. by importing `psycopg` at module scope, or by having the SQLite path reach for
the catalog to resolve an instrument id.

**Decision**: driver imports stay inside the adapters that need them (the warehouse branch's
`store/conn.py` already does this, raising `StoreNotConfigured` with an install hint rather than
`ImportError`), and the SQLite `ExperimentStore` adapter keys on symbol exactly as it does today. A
test asserts the demo path works with the Postgres and ClickHouse drivers unimportable.

## Note on sequencing

This feature carries the merge of `worktree-pg-historical-store` into `main`. The one conflicting
file is `backend/src/quantlab/api/routes.py`, where the workbench's direct-storage handlers meet the
backend abstraction; resolving it means porting the workbench routes onto the seam, which is the work
described above rather than a textual merge. `backend/contracts/openapi.yaml`, `schemas.py` and
`Makefile` auto-merged cleanly when trialled.
