# Implementation Plan: Modern Trading UI

**Branch**: `003-modern-trading-ui` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-modern-trading-ui/spec.md`

## Summary

Replace the Signal Viewer's hand-rolled SVG line chart with a real candlestick (OHLC) chart, add an
app-wide dark/light theme toggle that defaults to the OS preference and persists per browser, and
restyle the existing filters/table/status surfaces to a modern, consistent look — all without
changing the backend, the API contract, or any existing filter/sort/pagination/selection behavior.
Technical approach: adopt TradingView Lightweight Charts v5 for the candlestick panel and Tailwind
CSS + shadcn/ui for the dashboard shell and theming, on top of the existing React 18 + Vite +
TypeScript frontend — no framework migration, no backend changes.

## Technical Context

**Language/Version**: TypeScript 5.6, React 18.3 (existing frontend, unchanged)

**Primary Dependencies**: Vite 5 + `@vitejs/plugin-react` (existing); adding `lightweight-charts`
v5 (candlestick/volume rendering), Tailwind CSS + `shadcn/ui` (Radix-based, copied-in components)
for the dashboard shell and dark/light theming. `openapi-typescript` codegen against the existing
`002-signal-viewer-demo` OpenAPI contract is unchanged.

**Storage**: N/A for the app (frontend-only feature). Theme preference stored in the browser's
`localStorage`, keyed per device/browser (no user accounts exist).

**Testing**: Vitest + `@testing-library/react` + `jsdom` (existing). Extended with tests for the
theme provider/toggle and the candlestick chart wrapper; `lightweight-charts` requires mocking
`createChart` under `jsdom` since it draws to `<canvas>`, which `jsdom` does not implement.

**Target Platform**: Browser SPA, served the same way as today (Vite dev server locally; static
build behind nginx in `frontend/Dockerfile` / `docker-compose.yml`). No target platform change.

**Project Type**: Web application (existing `backend/` + `frontend/` split at the repository root).

**Performance Goals**: Chart pan/zoom stays smooth (no visible stutter) across at least several
years of daily OHLCV for one instrument (today's actual data scale); theme switch is applied to
the whole page in a single, immediate re-render with no visible flash of unstyled/wrong-theme
content.

**Constraints**: Frontend-only — no backend or OpenAPI contract changes (Constitution Principle V).
No new analytical computation in the frontend (Constitution Principle V / Technology Stack policy).
No new indicator overlays (out of scope per spec Assumptions). All existing `SignalsPage` behavior
(filtering, sorting, pagination, signal selection) must keep passing its existing tests unmodified
in intent. Desktop/tablet widths only, per spec.

**Scale/Scope**: One SPA page (Signal Viewer) restyled; a global theme applied across the whole
app; a single chart panel per selected signal, rendering up to a few thousand daily bars.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability | Assessment |
|---|---|---|
| I. Library-First | N/A | No new analytical functionality (data ingestion, indicators, screening, backtesting). This is presentation-only; no new "library" is introduced. |
| II. Pluggable Indicator & Derived-Data Architecture | N/A | No indicators added, changed, or removed. Spec explicitly excludes new indicator overlays. |
| III. Data Integrity & Free-Source Constraint | N/A | No data sources touched; existing OHLCV/signal data is only rendered, not fetched differently. |
| IV. Test-First (NON-NEGOTIABLE) | Applies | New components (theme provider/toggle, candlestick chart wrapper) get tests written first, extending the existing Vitest suite, before implementation — same as existing `SignalsPage`/`SignalTable`/`SignalFilters` tests. |
| V. Typed, Contract-Driven API Boundary | Applies — PASS | No new/changed API calls; the existing typed client (`openapi-typescript` output) is reused as-is. No analytical computation moves to the frontend — the chart only visualizes OHLCV fields the backend already returns. |
| VI. Reproducibility & Observability | N/A | No analytical computation changes. |
| VII. Point-in-Time Correctness (NON-NEGOTIABLE) | N/A | No new indicator or data logic that could leak future information. |
| Repository Structure (NON-NEGOTIABLE) | Applies — PASS | All implementation code lands under `frontend/` at the repo root; this feature's docs (spec/plan/research/data-model/contracts) stay under `quantlab_specs/specs/003-modern-trading-ui/`, which contains no code. |
| Technology Stack & Data Policy | Applies — PASS with justification | Frontend stays TypeScript, no client-side analytical computation. New dependencies (`lightweight-charts`, Tailwind, shadcn/ui) are presentation-only, permissively licensed (Apache-2.0 / MIT), and directly match what the spec asks for — see `research.md` for the justification of each. |

**Result**: No violations. No entries required in Complexity Tracking.

**Post-Phase 1 re-check**: Design artifacts (`research.md`, `data-model.md`,
`contracts/ui-contracts.md`) introduce one new client-side entity (Theme Preference, stored only in
`localStorage`) and two new internal component contracts (`ThemeProvider`/`useTheme`,
`CandlestickChart`); neither touches the backend, the OpenAPI contract, or adds analytical logic.
Gate result unchanged: **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/003-modern-trading-ui/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   └── ui-contracts.md   # Theme provider + chart component contracts (no API changes)
├── checklists/
│   └── requirements.md
└── tasks.md              # Phase 2 output (/speckit-tasks command — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
# Option 2: Web application (existing split — this feature only touches frontend/)
backend/
└── ...                       # UNCHANGED by this feature

frontend/
├── index.html
├── tailwind.config.ts        # NEW — Tailwind setup (dark mode via class strategy)
├── postcss.config.js         # NEW — required by Tailwind's Vite integration
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── styles.css            # REPLACED — Tailwind entry (@tailwind base/components/utilities)
│   │                          #   plus shadcn/ui CSS variables for light/dark palettes
│   ├── theme/                # NEW
│   │   ├── ThemeProvider.tsx #   context + localStorage + prefers-color-scheme default
│   │   └── ThemeToggle.tsx   #   the always-accessible light/dark switch (FR-005..FR-008)
│   ├── components/
│   │   ├── ui/                # NEW — shadcn/ui primitives copied in as owned code (button, card, table, etc.)
│   │   ├── PriceChart.tsx     # REPLACED by CandlestickChart.tsx (lightweight-charts wrapper)
│   │   ├── CandlestickChart.tsx # NEW — FR-001..FR-004, FR-011
│   │   ├── SignalFilters.tsx  # RESTYLED — same props/behavior, Tailwind/shadcn styling
│   │   ├── SignalTable.tsx    # RESTYLED — same props/behavior, Tailwind/shadcn styling
│   │   └── StatusStates.tsx   # RESTYLED — Loading/EmptyResults/BackendUnavailable in both themes
│   ├── api/                   # UNCHANGED — existing typed client against 002's OpenAPI contract
│   └── pages/
│       └── SignalsPage.tsx    # UNCHANGED behavior; wraps content with ThemeProvider layout
├── tests/
│   ├── fixtures.ts            # UNCHANGED
│   ├── SignalsPage.test.tsx   # UNCHANGED assertions (behavioral regression guard, FR-010)
│   ├── SignalTable.test.tsx   # UNCHANGED assertions
│   ├── SignalFilters.test.tsx # UNCHANGED assertions
│   ├── StatusStates.test.tsx  # UNCHANGED assertions
│   ├── CandlestickChart.test.tsx # NEW — mocks lightweight-charts createChart, asserts OHLCV data passed, marker date
│   └── ThemeProvider.test.tsx # NEW — default-from-system, persistence, toggle applies to <html> class
└── Dockerfile / nginx.conf / vite.config.ts / tsconfig.json  # UNCHANGED (Vite already runs Tailwind's PostCSS step automatically once configured)
```

**Structure Decision**: Reuse the existing Option 2 (web application) layout. This feature is
confined entirely to `frontend/`; `backend/` and the OpenAPI contract in
`specs/002-signal-viewer-demo/contracts/openapi.yaml` are untouched. `PriceChart.tsx` is replaced
by `CandlestickChart.tsx` rather than patched in place, since the rendering approach (SVG polyline
→ canvas-based candlestick library) is a full replacement, not an incremental edit.

## Complexity Tracking

*No Constitution Check violations — this section is intentionally empty.*
