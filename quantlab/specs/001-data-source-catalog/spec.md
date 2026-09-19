# Feature Specification: Data Source & Licensing Catalog

**Feature Branch**: `001-data-source-catalog`

**Created**: 2026-09-19

**Status**: Draft

## Clarifications

### Session 2026-09-19

- Q: What form should the catalog artifact take — human-readable versioned document only, or also
  a machine-readable registry? → A: Machine-readable registry (YAML/JSON in the repo) as the
  single source of truth, with the human-readable catalog generated from it (FR-010).
- Q: Does go-live require end-of-day data parity only, or also intraday/real-time data? → A:
  End-of-day parity only; intraday/real-time is out of scope for go-live substitution candidates
  (FR-011).

**Input**: User description: "Given many open questions on the data source/license, currently we want to pull the free source for now. Catalog the data input we are using now, and once go live what data we can substitute and its source."

## Context

QuantLab currently ingests market and reference data exclusively from free sources while licensing
questions remain open (see Constitution, Principle III). Stakeholders need a single, authoritative
catalog that answers two questions at any time:

1. **Now** — exactly which data inputs are in use, from which source, covering what, and under
   which usage terms and restrictions.
2. **Go-live** — for each input, what licensed/production-grade substitute can replace it, from
   which source, and what capability gaps the substitution must close.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Current Data Input Catalog (Priority: P1)

A developer, researcher, or reviewer opens the catalog and, for every data input currently
ingested, can see: the source, the data categories it provides, market/universe coverage, its role
(primary or fallback), update cadence, the license/terms classification, the permitted-use
boundary, and known limitations or gaps.

**Why this priority**: Without a complete, accurate picture of what is in use today and under
which terms, no licensing, compliance, or go-live decision can be made. This is the foundation
every other story builds on.

**Independent Test**: Can be fully tested by opening the catalog and verifying that every source
listed in the approved source stack (Constitution, Principle III) has a complete entry, and that a
reader can answer "what are we using, for what, under which terms" for any one of them without
leaving the catalog.

**Acceptance Scenarios**:

1. **Given** the catalog, **When** a stakeholder looks up the primary daily price input,
   **Then** they see the source, NYSE and LSE coverage, history depth, role as primary, its
   license classification, and its permitted-use boundary.
2. **Given** the catalog, **When** a stakeholder looks up the fallback price source,
   **Then** they see it flagged as fallback, its unique contributions (LSE coverage, UK corporate
   actions), its known instability, and its usage restrictions.
3. **Given** the catalog, **When** a stakeholder reviews fundamentals, identifiers, and FX inputs,
   **Then** each has a complete entry including documented coverage gaps (e.g., UK issuers
   incorporated in Jersey/Guernsey absent from the UK filings source).

---

### User Story 2 - Go-Live Substitution Mapping (Priority: P2)

For each current input, the catalog lists candidate substitutes suitable for production use: the
substitute source, its licensing status, a coverage comparison against the current input (history
depth, universe breadth, adjustments/corporate actions, currency handling), capability gaps the
substitution would open or close, and which parts of the system would be affected by the swap.

**Why this priority**: The constitution mandates that unofficial sources are dev/internal-research
only and that the UK side must move to a properly licensed feed before third-party serving. This
story turns that mandate into a concrete, comparable menu of options so a go-live licensing
decision can be made without re-researching the market from scratch.

**Independent Test**: Can be fully tested by filtering the catalog to inputs flagged "requires
substitution" and verifying each has at least one candidate substitute with a completed coverage
comparison.

**Acceptance Scenarios**:

1. **Given** an input sourced from an unofficial provider, **When** a stakeholder views its entry,
   **Then** they see at least one licensed substitute candidate, its licensing status, and a
   side-by-side coverage comparison.
2. **Given** the LSE price input, **When** a stakeholder reviews substitutes, **Then** the
   comparison explicitly covers LSE universe breadth, GBX-to-GBP handling, and corporate actions,
   since these are the known pain points of the current free stack.
3. **Given** an input already on a public-domain or official source, **When** a stakeholder views
   its entry, **Then** it is marked go-live ready with no substitution required, and any residual
   coverage gap is documented.

---

### User Story 3 - Catalog Governance & Go-Live Readiness Gate (Priority: P3)

The catalog is a versioned, reviewable artifact: each entry carries a last-reviewed date, terms
changes trigger re-review, and adding or changing any data source requires a catalog update. A
stakeholder can at any time produce the list of inputs that block go-live under the current
go-live definition.

**Why this priority**: Licenses and terms change, and new sources get added. Without governance
the catalog silently goes stale and stops being trustworthy exactly when it is needed most —
at the go-live decision.

**Independent Test**: Can be fully tested by checking that every entry carries provenance and
review metadata, and that the "go-live blockers" list is derivable from the catalog alone.

**Acceptance Scenarios**:

1. **Given** a source changes its terms of use, **When** the change is identified, **Then** the
   affected entry is updated and its review date refreshed before dependent decisions rely on it.
2. **Given** a proposal to add a new data source, **When** it is reviewed, **Then** a catalog
   entry covering terms and permitted use exists before the source is adopted.
3. **Given** any point in time, **When** a stakeholder requests go-live readiness, **Then** the
   set of blocking inputs (unofficial sources still in use) is produced from the catalog without
   manual research.

---

### Edge Cases

- A substitute candidate covers the data category but lacks a capability the free source uniquely
  provided (e.g., UK corporate actions, or deep 30+ year history) — the gap must be recorded as an
  open substitution risk, not silently dropped.
- A source changes its terms of use or shuts down after being cataloged — the entry must be marked
  stale and queued for re-review; dependent inputs remain flagged with their last-known terms.
- A free source's coverage gap (e.g., non-UK-incorporated LSE issuers) may persist after
  substitution if the licensed vendor has the same gap — the comparison must distinguish "gap
  closed by substitution" from "gap inherent to the market".
- Two current sources provide the same category (primary/fallback) — the substitution mapping must
  make clear whether one licensed feed replaces both roles.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The catalog MUST contain one entry for every data source currently ingested by the
  platform, covering at minimum the full approved source stack: primary daily prices (Stooq),
  fallback prices and UK corporate actions (Yahoo), US fundamentals (SEC EDGAR), UK filings
  (Companies House), identifier bridging (OpenFIGI), and GBP/USD FX (BoE IADB).
- **FR-002**: Each entry MUST record: source name; data categories provided; market and universe
  coverage; role (primary, fallback, or sole source for its category); update cadence; license
  classification; permitted-use boundary; and known limitations or coverage gaps.
- **FR-003**: Each entry MUST carry a license classification from a fixed vocabulary: *public
  domain / official*, *free with terms*, *unofficial (no redistribution rights)*, or
  *licensed / commercial*.
- **FR-004**: Each entry for an unofficial source MUST state the restriction (development and
  internal research only), the trigger that forbids continued use (redistribution, publication, or
  production deployment serving third parties, per Constitution Principle III), and MUST flag the
  input as "requires substitution".
- **FR-005**: Each entry MUST list candidate go-live substitutes, each with its source, licensing
  status, and whether it is exchange-official, a major licensed vendor, or another free source.
- **FR-006**: Each substitution mapping MUST include a coverage comparison against the current
  input — history depth, universe breadth, adjustments and corporate actions, and currency/unit
  handling (including GBX-to-GBP normalization for LSE data) — and MUST explicitly record any
  capability gap that substitution would open or fail to close.
- **FR-007**: Each entry MUST carry a go-live readiness determination: *go-live ready* or
  *requires substitution*, derived from its license classification and the project's go-live
  definition.
- **FR-008**: The catalog MUST be versioned, and each entry MUST carry provenance metadata
  (last-reviewed date, terms reference, reviewer).
- **FR-009**: Adoption of any new data source, or material change to an existing source's role or
  terms, MUST require a corresponding catalog entry or update before the change is accepted.
- **FR-010**: The catalog MUST be delivered as a machine-readable registry (structured YAML/JSON
  committed to the repository) that serves as the single source of truth, with the human-readable
  catalog generated from it. The registry MUST be queryable by the ingestion layer and tooling
  (e.g., to derive go-live blockers and to assert license restrictions at adapter definition
  sites); the two views MUST NOT be maintained independently.
- **FR-011**: Substitution candidates MUST satisfy go-live data requirements of end-of-day parity
  with the current stack (daily OHLCV prices, corporate actions, fundamentals, filings,
  identifiers, FX). Intraday or real-time data is NOT required at go-live; candidates offering
  only intraday/real-time value beyond EOD parity MAY be noted but are not required.

### Key Entities

- **Data Source Entry**: One external source currently ingested or proposed; attributes include
  data categories, coverage, role, cadence, license classification, permitted-use boundary,
  limitations, provenance, and go-live readiness.
- **Data Category**: A kind of data input (daily OHLCV prices, corporate actions, fundamentals,
  filings, identifiers, FX rates) that one or more sources may provide.
- **Substitution Candidate**: A potential replacement source for a data category, with licensing
  status, coverage comparison, and identified capability gaps.
- **License Classification**: The fixed vocabulary term describing usage rights for a source,
  which drives the permitted-use boundary and go-live readiness.
- **Go-Live Readiness**: The per-input determination of whether the current source may remain in
  use when the platform goes live, or must be substituted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of currently ingested data sources (the six approved-stack sources) have
  complete catalog entries; a stakeholder can answer "what source provides this data and under
  which terms" for any input in under 2 minutes.
- **SC-002**: 100% of inputs classified as unofficial have at least one identified licensed
  substitute candidate with a completed coverage comparison.
- **SC-003**: 100% of inputs carry an explicit go-live readiness determination, and the full list
  of go-live-blocking inputs can be produced from the catalog alone in under 5 minutes.
- **SC-004**: The substitution comparison for price data explicitly covers, for both NYSE and LSE:
  universe breadth, history depth, adjustments/corporate actions, and currency/unit handling.
- **SC-005**: Every entry carries review metadata; no entry is accepted without a license
  classification and permitted-use boundary.

## Assumptions

- The current data stack is exactly the approved source stack defined in Constitution Principle
  III (Stooq, Yahoo, SEC EDGAR, Companies House, OpenFIGI, BoE IADB); no other sources are
  currently ingested.
- The go-live trigger is as defined in the constitution: redistribution, publication, or
  production deployment serving third parties. Internal research and development use of free
  sources remains permitted.
- Substitution candidates are enumerated and compared in the catalog, but final vendor selection
  and procurement are business decisions outside this feature's scope.
- Candidate substitutes will be drawn from established options: exchange-official feeds and
  licensed market data vendors for prices and corporate actions, and official/continued use of
  public-domain sources (SEC EDGAR, Companies House, BoE IADB) where terms already permit the
  intended use.
- Known gaps in the current stack (unofficial status of Stooq/Yahoo, Companies House coverage gap
  for Jersey/Guernsey-incorporated LSE issuers, no stable free LSE instrument list) are carried
  into the catalog as documented limitations rather than re-derived.
