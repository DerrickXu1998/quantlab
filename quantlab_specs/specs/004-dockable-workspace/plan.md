# Implementation Plan: Dockable Workspace

**Branch**: `004-dockable-workspace` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-dockable-workspace/spec.md`

## Summary

Replace the Signal Viewer's fixed vertical stack with a docking workspace: the filters, signal list,
and price chart become panels users can drag-to-split, resize, tab together, float, close and reopen,
with the arrangement persisted per browser and resettable to a default. Technical approach: adopt
`dockview-react` v8.3.1 on the existing React 18 + Vite + TypeScript frontend, driving panel layout
through `DockviewApi.toJSON()`/`fromJSON()`, and — critically — replacing the chart's
ResizeObserver-based `autoSize` with explicit resizing driven by dockview's own
`onDidDimensionsChange` / `onDidVisibilityChange` panel events. No backend or API contract changes.

## Technical Context

**Language/Version**: TypeScript 5.6, React 18.3 (existing frontend, unchanged)

**Primary Dependencies**: Vite 5, `lightweight-charts` 5.2, Tailwind + shadcn-style primitives (all
existing, from `003-modern-trading-ui`); adding `dockview-react` ^8.3.1. Verified dependency chain:
`dockview-react` → `dockview` → `dockview-core`, all first-party packages, and `dockview-core` has
zero third-party runtime dependencies. `dockview-react` declares React 16.8–19 as peer dependencies,
so React 18.3.1 is supported.

**Storage**: N/A for the app (frontend-only). The serialized layout is stored in the browser's
`localStorage`, under its own key, alongside the existing theme key.

**Testing**: Vitest + `@testing-library/react` + `jsdom` (existing). Dockview measures real DOM boxes,
which jsdom reports as zero, so `DockviewReact` is mocked at the module boundary — the same
"mock the boundary, assert on the call" pattern already used for `lightweight-charts`. Layout
persistence, the panel registry, and the chart resize adapter are unit-tested as plain logic.

**Target Platform**: Browser SPA, served as today (Vite dev server; static build behind nginx).

**Project Type**: Web application (existing `backend/` + `frontend/` split; this feature touches
`frontend/` only).

**Performance Goals**: Dragging a divider resizes panels and redraws the chart without visible
stutter; rearranging panels triggers zero additional API requests (SC-007); layout writes to storage
are debounced so a drag does not cause a write per animation frame.

**Constraints**: Frontend-only — no backend or OpenAPI contract changes (Constitution Principle V).
All existing Signal Viewer behavior must be preserved (FR-010) and is guarded by the existing test
suites. The chart must never render blank, stale, or zero-height (FR-009/SC-004) — the primary
technical risk. Docking targets desktop widths, with a stacked fallback below.

**Scale/Scope**: Three panels today (filters, signal list, price chart), designed so adding a fourth
is a registry entry rather than a layout rewrite. One serialized layout per browser.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability | Assessment |
|---|---|---|
| I. Library-First | N/A | No new analytical functionality (ingestion, indicators, screening, backtesting). Presentation only. |
| II. Pluggable Indicator & Derived-Data Architecture | N/A | No indicators added or changed. |
| III. Data Integrity & Free-Source Constraint | N/A | No data sources touched; no change to what is fetched or how. |
| IV. Test-First (NON-NEGOTIABLE) | Applies | Layout persistence, default-layout fallback, panel registry, and the chart resize adapter get tests written first, extending the existing Vitest suite. |
| V. Typed, Contract-Driven API Boundary | Applies — PASS | No new or changed API calls; the generated typed client is untouched. No analytical computation moves client-side — this is pure layout. |
| VI. Reproducibility & Observability | N/A | No analytical computation changes. |
| VII. Point-in-Time Correctness (NON-NEGOTIABLE) | N/A | No indicator or data logic that could leak future information. |
| Repository Structure (NON-NEGOTIABLE) | Applies — PASS | All code lands under `frontend/`; this feature's documents stay under `quantlab_specs/specs/004-dockable-workspace/`, which holds no code. |
| Technology Stack & Data Policy | Applies — **PASS with justification** | Frontend stays TypeScript with no client-side analytics. `dockview-react` is a presentation-only dependency whose engine has zero third-party deps — but the dependency policy requires new libraries to be justified, and the YAGNI clause in Development Workflow requires justifying complexity beyond the simplest working design. See Complexity Tracking. |

**Result**: Passes, with one justified complexity entry recorded below rather than waved through.

**Post-Phase 1 re-check**: The design artifacts add one new persisted client-side entity (Workspace
Layout in `localStorage`), a panel registry, and a chart resize adapter. None touch the backend, the
OpenAPI contract, or analytical logic, and the chart adapter *reduces* reliance on implicit
ResizeObserver behavior in favour of explicit, testable events. Gate result unchanged: **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/004-dockable-workspace/
├── plan.md               # This file (/speckit-plan command output)
├── research.md           # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   └── ui-contracts.md   # Panel registry, layout store, chart resize adapter (no API changes)
├── checklists/
│   └── requirements.md
└── tasks.md              # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/
└── ...                            # UNCHANGED by this feature

frontend/
├── src/
│   ├── App.tsx                    # MODIFIED — shell hosts the workspace; keeps header + ThemeToggle
│   ├── styles.css                 # MODIFIED — import dockview CSS; map --dv-* vars to our tokens
│   ├── workspace/                 # NEW
│   │   ├── Workspace.tsx          #   DockviewReact host: registry, onReady, default layout, theme
│   │   ├── panels.tsx             #   panel id → component registry (filters, signals, chart)
│   │   ├── defaultLayout.ts       #   the default arrangement, also used by reset
│   │   ├── layoutStorage.ts       #   load/save/clear serialized layout + validation (FR-006/008)
│   │   └── useWorkspaceLayout.ts  #   wires onDidLayoutChange → debounced save, fromJSON on ready
│   ├── components/
│   │   ├── CandlestickChart.tsx   # MODIFIED — explicit resize via usePanelSize (FR-009)
│   │   ├── usePanelSize.ts        # NEW — subscribes to dockview panel dimension/visibility events
│   │   ├── SignalFilters.tsx      # UNCHANGED
│   │   ├── SignalTable.tsx        # UNCHANGED
│   │   └── StatusStates.tsx       # UNCHANGED
│   ├── pages/
│   │   └── SignalsPage.tsx        # MODIFIED — owns shared state, renders panels instead of a stack
│   ├── theme/                     # UNCHANGED (ThemeProvider/ThemeToggle from 003)
│   └── api/                       # UNCHANGED — typed client untouched
└── tests/
    ├── mocks/dockview-react.tsx   # NEW — mock DockviewReact (jsdom reports zero-size boxes)
    ├── layoutStorage.test.ts      # NEW — persistence, corrupt/outdated layout fallback
    ├── usePanelSize.test.tsx      # NEW — resize + hidden-tab behavior (the FR-009 guard)
    ├── Workspace.test.tsx         # NEW — panel registry, reset-to-default, reopen closed panel
    └── (existing suites)          # UNCHANGED assertions — the FR-010 regression guard
```

**Structure Decision**: Keep the existing web-application layout; all work is in `frontend/`. A new
`src/workspace/` module owns everything docking-related so the docking library stays behind a small
seam — panels themselves remain ordinary components that know nothing about dockview, which is what
keeps the existing component tests valid and would make a future library swap tractable.

## Complexity Tracking

> The constitution requires justifying complexity beyond the simplest working design (Development
> Workflow, YAGNI clause) and justifying new third-party libraries (Technology Stack & Data Policy).

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| A full docking manager for three panels | The product direction is an analyst-facing terminal where panel count grows (the spec's own Assumptions name positions, orders, analytics and multi-chart comparison as the expected next steps). Docking is substantially cheaper to adopt while there are three panels than to retrofit once there are eight, because retrofitting forces every panel to be rewritten for a new sizing model at once. | A fixed two-column responsive CSS grid genuinely satisfies today's three panels with no new dependency — and is the right answer **if** the multi-panel direction is abandoned. It was rejected only because it cannot deliver FR-002/FR-004/FR-006 (drag-to-split, tabbing, saved layouts), which are the user-visible point of this feature. This row is a standing flag: if the terminal direction changes, this dependency should be reconsidered rather than inherited. |
| New dependency: `dockview-react` | Building docking by hand (drag-to-split geometry, drop targets, tab groups, floating windows, serialization) is a large, bug-prone surface far exceeding the cost of adopting a maintained library. The engine has zero third-party runtime dependencies, so supply-chain surface is limited to first-party dockview packages. | Hand-rolled splitters were rejected because the effort is disproportionate and the result would be worse; heavier component kits (full IDE shells) were rejected as far more than the feature needs. |
