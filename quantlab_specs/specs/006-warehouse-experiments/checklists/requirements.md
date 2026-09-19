# Specification Quality Checklist: Warehouse-Backed Experiments

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-19
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- **This spec exists because a merge could not be resolved mechanically.** Feature 005's workbench
  talks to storage directly; the warehouse work routes handlers through a storage abstraction whose
  contract covers only instruments, prices and signals. Reconciling them touches identity modelling
  and data correctness, not just plumbing — which is why it is specified rather than patched into a
  merge commit.
- **Two hazards were found by reading the warehouse schema, not assumed**, and both drove
  requirements that would otherwise have been missed:
  - *Ticker reuse* (FR-007, SC-005). Vendor symbols bind to instruments only over date ranges,
    enforced by an exclusion constraint. A run resolving symbols as-of *today* would splice two
    different companies into one series across a long window — wrong, plausible-looking, and silent.
  - *Unadjusted bars* (FR-008, SC-004). Bars are stored unadjusted by deliberate design, with the
    vendor's adjusted close explicitly non-authoritative. A model run across a split sees an
    artefact. The spec requires corporate actions in the window to be *reported* rather than
    silently picking an adjustment policy, which is a genuine follow-up feature.
- **The signal-pollution trap from 005 recurs here** (FR-010, SC-007): the warehouse also keeps a
  materialised signals table that would accept exploratory run output cleanly and then surface it in
  the Signal Viewer. Same failure, different store.
- **Preserving the zero-setup demo is treated as a first-class story** (US2) rather than a footnote,
  because it is existing behaviour that this feature could easily cost, and a regression there is
  more damaging than a missing warehouse capability.
- Storage placement for runs (relational catalog, not the columnar bar store) is recorded as an
  assumption with reasoning rather than left to the plan, since it follows directly from the storage
  split the warehouse already documents.
- All items passed on the first validation pass; no clarification markers were needed, as each
  ambiguous point had a defensible default that is documented in Assumptions.
