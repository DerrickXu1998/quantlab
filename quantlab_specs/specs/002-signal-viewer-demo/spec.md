# Feature Specification: Dockerized Signal Viewer on Synthetic Data

**Feature Branch**: `002-signal-viewer-demo`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "we want to create 1. docker make file to set up the dockerized container 2. we want to add some fake data 3. add a ui to display the all signal on the fake data"

## Context

QuantLab is early-stage: the analytical stack (Python backend, TypeScript frontend, pluggable
indicator engine) is being stood up, and there is no real market data in the system yet. This
feature delivers an end-to-end runnable demo: a single-command Docker environment that seeds the
system with synthetic (fake) price data, computes a starter set of trading signals over that
data, and presents all signals in a web UI. Its purpose is to prove the vertical slice
(data → indicators/signals → API → UI) and to give developers a reproducible sandbox that does
not depend on any external data source, network access, or licensing.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One-Command Dockerized Environment (Priority: P1)

A developer clones the repository and, with a single documented command (via a Makefile target),
builds and starts the complete stack in Docker: backend service, frontend UI, and the synthetic
data seeding step. No other local tooling beyond Docker and `make` is required, and the same
command works on a fresh machine with no prior project setup.

**Why this priority**: Without a reproducible, self-contained runtime, nothing else in this
feature — fake data or the UI — can be demonstrated or tested by anyone but the original author.
This is the foundation of the demo.

**Independent Test**: Can be fully tested on a clean checkout by running the single make target
and verifying that all services come up healthy, synthetic data is seeded automatically, and the
UI is reachable in a browser.

**Acceptance Scenarios**:

1. **Given** a fresh clone on a machine with only Docker and make installed, **When** the
   developer runs the documented setup command, **Then** the backend, frontend, and seed step
   build and start without manual intervention, and the UI loads in a browser.
2. **Given** the stack is already running, **When** the developer runs the teardown target,
   **Then** all containers stop and are removed, and a subsequent setup brings back a clean,
   re-seeded environment.
3. **Given** the stack was previously seeded, **When** the developer restarts it, **Then** the
   synthetic dataset is identical (deterministic seed), so any signal seen before restart is
   still present.

---

### User Story 2 - Synthetic Market Data with Computed Signals (Priority: P2)

The system ships with a synthetic dataset: a small, fixed universe of fictitious instruments
with multi-year daily price histories whose statistical properties (trending, mean-reverting,
volatile regimes) are deliberately varied so that the starter signal rules actually fire. On
seed, the backend computes the full set of signals over this data and stores them with the
instrument, date, signal type, direction, and the values that triggered them.

**Why this priority**: Fake data is what makes the demo independent of external sources and
licensing (Constitution, Principle III does not apply to synthetic data), and deterministically
generated data with known properties is what makes the computed signals verifiable and
reproducible (Principle VI). Without it the UI would have nothing meaningful to show.

**Independent Test**: Can be fully tested without the UI by seeding the dataset and querying the
signals through the backend API: the same seed produces the same dataset and the same signal
set every time, and every emitted signal can be re-derived from the price data plus the signal
rule definition.

**Acceptance Scenarios**:

1. **Given** a clean environment, **When** the seed step runs, **Then** a fixed universe of
   fictitious instruments with deterministic daily price histories exists, and signals are
   computed and stored for all of them.
2. **Given** the seeded dataset, **When** the seed step is run again, **Then** the dataset and
   the computed signal set are byte-identical to the previous run (no hidden randomness or
   wall-clock dependence).
3. **Given** the seeded dataset, **When** any stored signal is inspected, **Then** it carries
   the instrument, signal date, signal type, direction, and the indicator values that triggered
   it, and those values can be reproduced from the price history alone.

---

### User Story 3 - Signal Viewer UI (Priority: P3)

A user opens the web UI and sees all signals computed over the synthetic dataset in a single
view. Each signal row shows the instrument, date, signal type, direction (long/short or
bullish/bearish), and triggering values. The user can filter and sort the list by instrument,
signal type, direction, and date range, and can select a signal to see it in the context of the
instrument's price history.

**Why this priority**: The UI is the visible payoff of the demo and the first exercise of the
typed API boundary (Constitution, Principle V) — it proves a thin frontend can consume backend
analytics. It depends on Stories 1 and 2 but is independently testable against the seeded
backend.

**Independent Test**: Can be fully tested by pointing a browser at the running stack and
verifying that the number of signals shown matches the backend's signal count, filters narrow
the list correctly, and selecting a signal shows its context on the price history.

**Acceptance Scenarios**:

1. **Given** the seeded, running stack, **When** the user opens the UI, **Then** all computed
   signals are listed with instrument, date, type, direction, and triggering values, and the
   total count matches what the backend reports.
2. **Given** the signal list, **When** the user filters by an instrument and a date range,
   **Then** only matching signals remain and the displayed count updates accordingly.
3. **Given** the signal list, **When** the user selects a signal, **Then** the instrument's
   price history is shown with the selected signal marked at its date.

---

### Edge Cases

- Docker is unavailable or a port is already in use: the setup command fails fast with a clear,
  actionable message rather than hanging or half-starting the stack.
- The seed step is interrupted mid-run: re-running setup produces the complete deterministic
  dataset, never a partially seeded one.
- A synthetic price history is too short for a signal rule's lookback window: no signal is
  emitted for the insufficient period, and this is expected behavior, not an error.
- The user applies filters that match no signals: the UI shows an explicit empty state rather
  than a blank or broken view.
- The backend is unreachable when the UI loads: the UI shows a clear error state instead of an
  empty list that looks like "no signals".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST provide a Makefile with a single documented target that builds
  and starts the full stack (backend, frontend, data seeding) as Docker containers, plus targets
  to stop/teardown the stack and to view service health.
- **FR-002**: The Docker setup MUST require only Docker and make on the host; all language
  toolchains, dependencies, and build steps MUST run inside containers.
- **FR-003**: Seeding MUST run automatically as part of stack startup, MUST be idempotent, and
  MUST complete before the backend accepts signal queries.
- **FR-004**: The system MUST generate a synthetic dataset of a fixed universe of at least 10
  fictitious instruments, each with at least 3 years of daily OHLCV price history, with
  deliberately varied regimes (trending, mean-reverting, volatile) so that every starter signal
  rule fires at least once somewhere in the dataset.
- **FR-005**: Synthetic data generation MUST be fully deterministic: the same configuration
  always produces byte-identical data, with no dependence on wall-clock time or unseeded
  randomness.
- **FR-006**: Synthetic instruments and prices MUST be clearly fictitious (recognizably fake
  names/symbols) and MUST NOT be presented anywhere as real market data.
- **FR-007**: The backend MUST compute a starter set of at least 3 distinct rule-based signal
  types (e.g., moving-average crossover, overbought/oversold threshold, breakout) over the
  synthetic data at seed time, each with a declared direction, and MUST store each signal with
  instrument, date, type, direction, and the indicator values that triggered it.
- **FR-008**: Signal computation MUST follow the constitution's analytical constraints: computed
  in the backend only, reproducible from raw data plus deterministic logic, and free of
  look-ahead (a signal dated day T uses only data knowable by day T).
- **FR-009**: The backend MUST expose the full signal set and per-instrument price histories to
  the frontend through the typed, schema-defined API boundary; the frontend MUST NOT compute
  indicators or signals itself.
- **FR-010**: The UI MUST display all signals in a list showing instrument, date, type,
  direction, and triggering values, with the total signal count visible.
- **FR-011**: The UI MUST support filtering by instrument, signal type, direction, and date
  range, and sorting by date, with the displayed count reflecting the active filters.
- **FR-012**: The UI MUST let the user select a signal and view the instrument's price history
  with the signal marked at its date.
- **FR-013**: The UI MUST present explicit states for loading, empty filter results, and backend
  unavailability, each visually distinct.

### Key Entities

- **Synthetic Instrument**: A fictitious tradable instrument in the demo universe; attributes
  include a recognizably fake symbol/name and a deterministic daily OHLCV price history.
- **Price History**: The daily open/high/low/close/volume series for one synthetic instrument,
  generated deterministically and stored as the raw input to signal computation.
- **Signal Rule**: A named, versioned rule (per the plugin contract) that maps an instrument's
  price history to zero or more signal events; declares its lookback window, parameters, and
  direction semantics.
- **Signal**: One emitted event; attributes include instrument, date, rule/type, direction,
  and the indicator values that triggered it, stored with provenance (rule name/version,
  parameters).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer on a clean machine can go from `git clone` to viewing signals in the
  UI in under 10 minutes, running no more than 2 commands.
- **SC-002**: Two independent setups of the stack produce identical datasets and identical
  signal sets — 100% of signals match on instrument, date, type, and direction across runs.
- **SC-003**: The seeded dataset contains at least 10 instruments × 3 years of daily data, and
  every starter signal rule fires at least once in the dataset.
- **SC-004**: The UI's displayed signal count matches the backend's total signal count exactly,
  and any filter combination's count matches a direct backend query with the same criteria.
- **SC-005**: Every displayed signal can be independently re-derived from the stored price
  history and its rule definition, with zero discrepancies on a full sweep.

## Assumptions

- "Signals" means rule-based trading signals derived from indicators computed on the synthetic
  price data (e.g., moving-average crossover, overbought/oversold threshold, breakout); a small
  starter set of well-known rules is sufficient for this demo — no user-defined or
  machine-learning signals are in scope.
- "Docker make file" means a Makefile whose targets drive the containerized stack (build, up,
  down, logs/health); the container orchestration tool underneath is a plan-phase decision.
- The demo runs entirely locally; no external network access or real data source is required or
  permitted for this feature, so the free-source licensing constraints (Constitution,
  Principle III) do not apply to the synthetic data.
- The UI is a read-only viewer: filtering, sorting, and signal context are in scope; editing,
  creating rules from the UI, alerting, and user accounts are out of scope.
- The dataset size (≥10 instruments, ≥3 years daily) is a floor chosen to be small enough for
  fast seeding and large enough to exercise every signal rule.
- This feature builds on the project's intended stack (Python backend, TypeScript frontend per
  the constitution); since the repository has no application code yet, this feature includes
  standing up the minimal backend/frontend skeleton needed for the vertical slice.
