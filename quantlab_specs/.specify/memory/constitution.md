# QuantLab Constitution

## Core Principles

### I. Library-First

Every piece of analytical functionality (data ingestion, indicator computation, derived-data
generation, screening, backtesting support) MUST start as a self-contained, independently
testable library with a clear public interface. No feature logic may live only inside HTTP
handlers, UI components, or scripts. Libraries must have a documented purpose; organizational
"bucket" libraries with no coherent responsibility are forbidden.

Rationale: Quantitative logic must be reusable, testable in isolation, and safe to reuse across
the API layer, batch jobs, and future research tooling.

### II. Pluggable Indicator & Derived-Data Architecture

All technical indicators and derived-data computations MUST be implemented as plugins behind a
common, versioned contract: each plugin declares its name, version, input schema, output schema,
and parameters, and registers itself without modifying the core engine. Adding, removing, or
upgrading an indicator MUST NOT require changes to unrelated code. The plugin registry MUST
support discovery at runtime so the frontend can enumerate available indicators and their
parameter metadata.

Three extension levels are supported, all landing in the same registry: an in-process decorator
(for notebooks and research), a `.py` file dropped into a plugin directory, and packaged entry
points where `pip install` is the entire install step.

Every indicator plugin MUST declare its scale class — scale-free (ratio/unitless, comparable
across names) or price-scaled (inherits the instrument's currency/price units) — so
cross-sectional analysis never mixes a $400 NYSE name with a 90p LSE line in price units.

Derived features that depend on external sources MUST degrade to NaN with a warning when their
source is unavailable, rather than failing the run.

Rationale: The indicator set will evolve constantly; a plugin contract keeps the core stable and
lets new analysis ship without touching the engine. Scale tagging and graceful degradation keep
panels comparable and pipelines resilient.

### III. Data Integrity & Free-Source Constraint (NON-NEGOTIABLE)

Market data MUST be ingested only from sources whose terms of use permit the intended use.
Every data source is an isolated adapter behind a common ingestion interface with: explicit
rate-limit handling, retry/backoff, and provenance metadata (source, symbol universe, timestamp,
and corporate-action/adjustment flags) stored alongside the data. Raw ingested data MUST be
persisted before any transformation, and derived values MUST be reproducible from raw data plus
deterministic plugin logic. No silent data mutations.

The approved source stack is:
- **Stooq** — primary daily OHLCV for both NYSE and LSE universes (no key, 30+ years history).
- **Yahoo (yfinance)** — fallback; best LSE coverage and the only free source of UK corporate
  actions. Known to break periodically; never the primary.
- **SEC EDGAR** — US fundamentals (public domain; `frames` endpoint for cross-filer concepts).
- **Companies House** — UK financials (acknowledged gap: ~10–20% of LSE issuers are
  Jersey/Guernsey-incorporated and absent).
- **OpenFIGI** — identifier bridge between sources.
- **BoE IADB** — GBP/USD FX for cross-market comparability.

Licensing stance: Stooq and Yahoo are unofficial sources with no redistribution rights. Their
use is permitted for development and internal research only; before any redistribution,
publication, or production deployment serving third parties, the UK side MUST move to a
properly licensed feed. Every adapter for an unofficial source MUST document this restriction
at its definition site and remain swappable for a licensed replacement without core changes.

Currency normalization: LSE quotes in pence (GBX) MUST be normalized to GBP at the adapter
boundary, before any data leaves the ingestion layer. Mixing GBX and GBP corrupts every
cross-sectional number by 100×; this is a correctness bug, not a formatting choice.

Survivorship bias: there is no free fix. The universe membership (symbols listed on each
exchange) MUST be snapshotted on every refresh from day one, so historical universes can be
reconstructed later. The LSE instrument list has no stable free endpoint; it is downloaded
manually from the LSE reports page and supplied by path, with the bundled FTSE fallback list
used only as a bootstrap default.

Rationale: Quantitative conclusions are only as trustworthy as their data lineage; free sources
have rate limits, licensing limits, and unit quirks that must be contained in adapters, not
leaked into analysis code.

### IV. Test-First (NON-NEGOTIABLE)

TDD is mandatory for analytical and data code: tests are written first, approved by the
implementer, shown to fail, then implementation proceeds (Red-Green-Refactor). Indicator
plugins MUST include correctness tests against known reference values (independently written
references, or simulated processes with known ground truth — e.g., Hurst against simulated
trending/mean-reverting series, half-life against a simulated OU process) and boundary cases
(insufficient history, gaps, nulls). Data adapters MUST be tested against recorded fixtures
rather than live network calls. Currency normalization (GBX→GBP) MUST have explicit tests.

Rationale: A wrong indicator value looks exactly like a right one; only verified reference
tests catch silent numerical errors — including seeding bugs that persist for hundreds of bars.

### V. Typed, Contract-Driven API Boundary

The TypeScript frontend and Python backend communicate exclusively through versioned,
schema-defined API contracts. Request/response shapes MUST be typed on both sides, generated or
mirrored from a single source of truth where feasible. The frontend MUST NOT embed analytical
computation; all computation happens in the backend so results stay consistent and testable.

Rationale: Two-language stacks drift without explicit contracts; a typed boundary keeps the UI
thin and the analytics authoritative.

### VI. Reproducibility & Observability

Every analytical result MUST be reproducible: given the same raw data, plugin versions, and
parameters, outputs are byte-identical. No hidden randomness, no dependence on wall-clock time
inside computations. Structured logging is required across ingestion and computation paths;
ingestion runs MUST record symbols processed, failures, and rate-limit events.

Rationale: Quantitative analysis that cannot be reproduced cannot be trusted, debugged, or
compared over time.

### VII. Point-in-Time Correctness (NON-NEGOTIABLE)

No feature may use information before it was knowable. Fundamentals MUST be stamped at filing
date, not reporting-period end. Every externally sourced feature MUST declare a publication lag,
and the engine applies that lag per symbol. Correctness is enforced by test, not by review: an
automated sweep MUST recompute every indicator on truncated history to detect accidental
look-ahead, and it runs in the standard test suite.

Rationale: Look-ahead bias is the most common and most expensive class of error in quantitative
research; it produces backtests that cannot be traded.

## Repository Structure (NON-NEGOTIABLE)

`quantlab_specs/` is the specification workspace and MUST contain no code. It holds exactly
the Spec Kit toolchain (`.specify/`) and the numbered feature specifications (`specs/`).
Source files, tests, build manifests, Dockerfiles, and dependency lockfiles MUST NOT be added
under it. Artifacts that a spec legitimately owns — OpenAPI documents, JSON Schemas, fixture
data referenced by the spec — are contracts, not code, and belong in the feature's
`contracts/` directory.

Runnable code lives at the repository root: the `quantlab` library in `src/` with its `tests/`,
and the demo application in `backend/` and `frontend/` with its `Makefile`,
`docker-compose.yml`, and `scripts/`.

There MUST be exactly one Spec Kit installation in the repository. `.specify/` exists only
inside `quantlab_specs/`, which makes that directory the Spec Kit project root, so
`create-new-feature.sh` resolves `$REPO_ROOT/specs` to `quantlab_specs/specs`. A second
`.specify/` elsewhere in the tree silently splits feature numbering and gives the project two
divergent constitutions; this is forbidden.

Every artifact has exactly one authored home, and a duplicate that a build constraint forces
MUST be generated from that home and guarded against drift by an automated check, never
hand-maintained. The OpenAPI contract is the worked example: it is authored once under the
feature's `contracts/` directory, and the copy inside `backend/contracts/` — which exists only
because the backend image's Docker build context is `backend/` and cannot reach outside it —
is refreshed by `make sync-contract` and verified by `make check-contract`, which runs as part
of `make test`.

Rationale: specifications and implementations have different review rules, different change
cadences, and different audiences; mixing them invites edits to a spec that are really code
changes in disguise. Nested scaffolding is worse than redundant — duplicated Spec Kit roots and
duplicated constitutions diverge silently, and a hand-copied contract drifts from the document
it is supposed to certify.

## Technology Stack & Data Policy

- Backend: Python (analytics, ingestion, indicator engine, API). The package is runnable and
  ships with its full test suite and lint gate; both must pass before merge.
- Frontend: TypeScript (visualization and analysis UI; no analytical computation client-side).
- Data sources: the approved stack in Principle III. New sources are added only as isolated
  adapters; sources with hard limits that make universe-scale coverage infeasible (symbol caps,
  daily call caps, truncated history) are rejected with documented reasons.
- Universe snapshotting: exchange membership snapshots are taken on every refresh and stored
  immutably (see Principle III).
- Storage: raw ingested data is persisted immutably; derived data is stored with provenance
  (plugin name/version, parameters, source data window, publication lag applied).
- Performance expectation: a full ~5,000-name refresh is bounded at roughly 10–15 minutes of
  compute plus rate-limit-dominated fetch time; changes that materially regress this need
  justification in the plan.
- Dependencies: new third-party libraries must be justified against the plugin and adapter
  contracts; heavy or license-restricted dependencies require explicit approval.

## Development Workflow

- All work follows the Spec Kit flow: specification → plan → tasks → implementation.
- Tests are written before implementation per Principle IV; analytical changes require
  reference-value or simulated-ground-truth tests, and the look-ahead sweep (Principle VII)
  must pass.
- Code review MUST verify: plugin contract conformance for indicators (including scale class
  and publication lag declarations), adapter isolation and rate-limit handling for data
  sources, GBX→GBP normalization at adapter boundaries, provenance metadata on derived data,
  no analytical logic in the frontend, and no code added under `quantlab_specs/`.
- Complexity beyond the simplest working design (YAGNI) must be justified in the plan.

## Governance

This constitution supersedes all other project practices. Amendments require: a documented
rationale, an explicit version bump per semantic versioning (MAJOR for backward-incompatible
principle removals or redefinitions, MINOR for new principles or materially expanded sections,
PATCH for clarifications and wording fixes), and a migration note where existing code is
affected. All pull requests and reviews MUST verify compliance with the principles above;
violations block merge unless a justified exception is recorded in the plan.

**Version**: 1.2.0 | **Ratified**: 2026-09-19 | **Last Amended**: 2026-09-19
