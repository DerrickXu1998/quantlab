# Feature Specification: Warehouse-Backed Experiments

**Feature Branch**: `006-warehouse-experiments`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "Run signal-discovery experiments against the real historical warehouse instead of only the synthetic SQLite demo... the workbench additionally needs windowed multi-symbol bar loading, per-instrument earliest-bar dates for warm-up coverage, and persistence for experiment runs and their produced signals... with the synthetic demo continuing to work unchanged when no warehouse is configured."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a Model Over Real Ingested History (Priority: P1)

A quant researcher who has ingested real market history wants to point a registered model at real
instruments over a real date range and see the signals it produces — the same workbench loop they
already have, but answering a question about actual markets rather than synthetic demo data.

**Why this priority**: This is the entire point. The workbench today can only answer "what would this
model do on fabricated data", which is a demonstration, not research. Everything else in this feature
exists to make this answer trustworthy.

**Independent Test**: With history ingested, open the workbench, select instruments from the real
universe and a date range covering ingested coverage, run a model, and confirm the resulting signals
are derived from real bars — verifiable by checking a reported signal against the underlying price
history for that instrument and date.

**Acceptance Scenarios**:

1. **Given** real history has been ingested, **When** the researcher opens the instrument selection,
   **Then** they see instruments from the real universe, not the synthetic demo set.
2. **Given** a model and a selection of real instruments and dates, **When** the run completes,
   **Then** the signals returned were computed from the ingested bars for those instruments in that
   window.
3. **Given** a completed run, **When** the researcher inspects it, **Then** it records which dataset
   it ran against, so a warehouse result is never mistaken for a demo result.
4. **Given** a run over a window wider than the ingested coverage for some instruments, **When** it
   completes, **Then** coverage reporting reflects what data actually existed, as it does today.
5. **Given** the same model, parameters, instruments and window, **When** the run is repeated against
   unchanged ingested data, **Then** the results are identical.

---

### User Story 2 - The Demo Still Works With No Warehouse (Priority: P2)

Someone cloning the project with no databases, no credentials and no network wants `make up` to
produce a working workbench on synthetic data, exactly as it does today.

**Why this priority**: The zero-setup demo is what makes the project approachable, and it is existing
behaviour that this feature must not cost. It is P2 only because it is preservation rather than new
capability — but a regression here is more damaging than a missing warehouse feature.

**Independent Test**: With no warehouse configured, start the stack and complete the full workbench
loop — browse models, configure parameters, run, inspect results, save an experiment — confirming
every step behaves as it does today.

**Acceptance Scenarios**:

1. **Given** no warehouse is configured, **When** the application starts, **Then** it serves the
   synthetic dataset without error and without requiring any database to be reachable.
2. **Given** the synthetic dataset is in use, **When** the researcher runs an experiment, **Then**
   the full workbench loop behaves exactly as it does today.
3. **Given** a warehouse is configured but unreachable at startup, **When** the application starts,
   **Then** it reports the problem clearly rather than appearing healthy while serving nothing.
4. **Given** the researcher is unsure which dataset is live, **When** they look at the workbench,
   **Then** the active dataset is identifiable without reading configuration or logs.

---

### User Story 3 - Experiments Stay Trustworthy Across Datasets (Priority: P3)

A researcher who has accumulated saved experiments wants to reopen them later and know exactly what
each one was computed from, and be told plainly when a result cannot be reproduced rather than
getting a quietly different answer.

**Why this priority**: Provenance is what separates a research tool from a toy, and this feature
introduces a second possible data source — the first opportunity for two runs to look comparable
while having been computed from entirely different data. Valuable, but the loop works without it.

**Independent Test**: Save an experiment run against one dataset, switch the configured dataset,
reopen the saved run, and confirm its recorded provenance is intact and it is clearly marked as not
reproducible under the current configuration.

**Acceptance Scenarios**:

1. **Given** a saved run, **When** it is reopened, **Then** its configuration and results are
   readable regardless of which dataset is currently active.
2. **Given** a run saved against one dataset, **When** the active dataset is a different one,
   **Then** the run is clearly marked as not re-runnable as recorded.
3. **Given** two runs being compared, **When** they were computed from different datasets, **Then**
   that difference is surfaced as prominently as a model-version difference.
4. **Given** a run against ingested history, **When** its provenance is inspected, **Then** it
   identifies the ingested data it used precisely enough to distinguish it from a later re-ingest of
   the same window.

---

### Edge Cases

- **Ticker reuse is the sharpest hazard.** In the warehouse a vendor ticker is bound to an instrument
  only over a date range — tickers get reused and reassigned (FB→META, and dead tickers handed to
  unrelated companies). A run must resolve the researcher's chosen symbols to instruments **as of the
  run window**, not as of today, or a long backtest silently splices two different companies into one
  price series.
- **Corporate actions inside the window.** Stored bars are unadjusted, and the vendor's adjusted
  close is explicitly not authoritative. A model run across an unadjusted split sees a price
  discontinuity that is an artefact, not a market move. The run MUST make any corporate action
  overlapping the window visible, so a nonsense result is recognisable as one.
- **An instrument in the catalog with no bars in the window** must be reported through coverage, not
  silently dropped from the denominator.
- **The warehouse becomes unreachable mid-run** must surface as a failed run with its reason and the
  researcher's configuration preserved, never as an empty successful result.
- **Selection size** matters far more here: the real universe can be thousands of instruments across
  decades, where the demo is twelve instruments over three years. An over-large request must be
  refused up front with the limit stated.
- **Mixed-currency selections** (a US and a London instrument together) must not present values as
  though they share a unit.
- **Experiment output must not enter the materialised signal set.** The warehouse already keeps a
  signals table described as a rebuildable cache of registry output; exploratory run output inserted
  there would surface in the Signal Viewer, exactly as it would have in the demo store.
- **A re-ingest of the same window between two runs** changes the underlying data while every input
  the researcher chose stays identical — the two runs must be distinguishable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The workbench MUST be able to run a registered model over instruments and a date range
  drawn from real ingested history.
- **FR-002**: The system MUST serve the synthetic dataset, with the full workbench loop intact, when
  no warehouse is configured — requiring no database, credentials or network.
- **FR-003**: The system MUST make the active dataset identifiable to the researcher in the interface.
- **FR-004**: When a warehouse is configured but unavailable, the system MUST report that plainly
  rather than presenting itself as healthy.
- **FR-005**: Every run MUST record which dataset it was computed against, as part of the provenance
  it already records.
- **FR-006**: A run against ingested history MUST record enough about that data to distinguish it
  from a later re-ingest of the same window.
- **FR-007**: Symbols selected by the researcher MUST be resolved to instruments as of the run's date
  window, so a reused ticker never merges two instruments into one series.
- **FR-008**: A run MUST report any corporate action affecting a selected instrument inside the run
  window.
- **FR-009**: Coverage reporting MUST continue to state how many selected instruments had data and
  how many had full warm-up history, against real history as it does against the demo data.
- **FR-010**: Experiment run output MUST be stored separately from any materialised or curated signal
  set, so exploratory runs never appear in the Signal Viewer.
- **FR-011**: Runs and saved experiments MUST persist and remain readable independently of which
  dataset is currently active.
- **FR-012**: A saved run whose recorded dataset is not the active one MUST be readable and clearly
  marked as not re-runnable as recorded.
- **FR-013**: When two compared runs used different datasets, the system MUST surface that as
  prominently as a model-version difference.
- **FR-014**: Repeating a run against unchanged ingested data MUST produce identical results.
- **FR-015**: A run that fails MUST report the reason and preserve the researcher's configuration.
- **FR-016**: The system MUST refuse a selection larger than a stated limit before running.
- **FR-017**: All existing behaviour MUST be preserved: model catalog, parameter validation, run
  execution, results, comparison and saved experiments continue to work as they do today.
- **FR-018**: All execution MUST remain outside the user interface; the interface configures runs and
  displays results.

### Key Entities

- **Dataset**: Which store a run was computed against — the synthetic demo set or ingested history.
  Recorded on every run; the thing that makes two otherwise-identical runs incomparable.
- **Instrument** *(warehouse)*: A company or security with a stable identity independent of any
  ticker. Vendor symbols bind to it only over date ranges, which is what makes as-of resolution
  necessary rather than optional.
- **Ingested Data Reference**: What a run used from the warehouse, precise enough that a later
  re-ingest of the same window is distinguishable.
- **Corporate Action**: A split or dividend affecting an instrument on a date. Not applied to stored
  bars; reported when it falls inside a run's window.
- **Experiment Run**, **Run Result**, **Saved Experiment**, **Model**, **Parameter Definition**
  *(existing)*: Unchanged in meaning, extended only by the dataset and data-reference provenance
  above.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A researcher with ingested history can run a model over real instruments and read its
  signals without changing any configuration mid-session.
- **SC-002**: Cloning the project and starting it with no databases, credentials or network produces
  a working workbench, with every step of the loop succeeding.
- **SC-003**: 100% of runs record which dataset produced them; no run exists whose data source is
  ambiguous.
- **SC-004**: A run whose window contains a corporate action always reports it, so no split-distorted
  result is presented as clean.
- **SC-005**: Symbol-to-instrument resolution is correct for 100% of runs whose window spans a ticker
  reassignment — verified against a known reused ticker.
- **SC-006**: Repeating any recorded run against unchanged ingested data reproduces its results
  identically.
- **SC-007**: Exploratory run output never appears in the Signal Viewer — verified by comparing the
  viewer's signal count before and after a run.
- **SC-008**: A researcher comparing two runs can always tell whether they were computed from the
  same data, without inspecting configuration files.

## Assumptions

- **Experiment runs and their output are stored in the relational catalog, not the columnar bar
  store.** Runs are small, mutable and want constraints and foreign keys; bars are enormous and
  append-only. This follows the storage split the warehouse already documents — anything with
  bar-level cardinality goes to the columnar store, anything needing a constraint stays relational.
- **Runs read the stored, unadjusted bars.** Adjustment is deliberately derived rather than stored,
  because a vendor's adjusted close is its opinion on the day it was fetched and silently poisons
  backtests. Rather than pick an adjustment policy here, this feature makes corporate actions in the
  window *visible* (FR-008). Applying an as-of adjustment factor to a run is a genuine follow-up
  feature and is out of scope.
- **The two data sources are alternatives, not a blend.** A single run draws entirely from one
  dataset; there is no merging of demo and ingested data, which keeps provenance meaningful.
- **Instrument selection remains an explicit choice by the researcher**, not an automatic universe
  sweep. Running the full universe is a scale problem with its own requirements and is out of scope.
- **Ingesting data is out of scope.** This feature consumes what the existing ingest path produced;
  it adds no sources, adapters or scheduling.
- **No new analytical capability.** The same registered models with the same parameters run against
  different data. Adding indicators, adjustment policies or backtest metrics is separate work.
- **Single-user, no authentication**, as throughout the project.
- **The synthetic demo path remains the default** so the zero-setup experience is preserved; the
  warehouse is opt-in through configuration.
