# Phase 0 Research: Modern Trading UI

No `[NEEDS CLARIFICATION]` markers remained in the Technical Context — the feature description
itself supplied a detailed technology survey. This document records the decisions made from that
survey against this project's actual constraints (existing React/Vite frontend, daily-bar-scale
data, Python backend that must stay untouched per Constitution Principle V), and the alternatives
rejected.

## Decision: Chart engine — TradingView Lightweight Charts v5

**Rationale**: The spec's core ask (FR-001..FR-004) is a real candlestick/OHLC panel with pan,
zoom, crosshair/hover readout, and a signal-date marker — not a general plotting surface. Lightweight
Charts is purpose-built exactly for this: canvas-based (handles the smooth pan/zoom in FR-011/SC-004
that the current SVG polyline cannot), ~45KB, Apache-2.0 (no licensing friction), and ships a
first-class candlestick series plus volume panes and crosshair out of the box, so the marker overlay
(equivalent to today's `markerDate` behavior in `PriceChart.tsx`) is a straightforward series marker
rather than hand-rolled SVG geometry.

**Alternatives considered**:
- **KLineChart** — rejected. Its main advantage (built-in MA/MACD/BOLL/RSI indicators and drawing
  tools) is exactly the capability the spec's Assumptions explicitly put out of scope (no new
  indicator overlays). Adopting it would pull in and expose UI for capability this feature doesn't
  need.
- **Apache ECharts** — rejected. It's the right tool when a candlestick is one panel among many
  analytics visual types (treemaps, heatmaps, large scatter) on a broader page. This feature has
  exactly one chart panel; ECharts' generality is unused weight here, and its candlestick primitive
  is not as purpose-fit as a dedicated trading chart library.
- **Highcharts Stock / AG Charts Enterprise** — rejected. Commercial licensing is unjustified for a
  synthetic-data internal demo app; the Technology Stack & Data Policy section requires justifying
  heavy/license-restricted dependencies, and a paid license buys range selectors/navigator bars this
  feature doesn't ask for.
- **Recharts / Nivo / Chart.js** — rejected outright. SVG-based, no real candlestick primitive, and
  known to degrade past a few thousand points — directly conflicts with FR-011/SC-004 (smooth
  pan/zoom over several years of daily bars).

## Decision: Dashboard shell — Tailwind CSS + shadcn/ui

**Rationale**: The existing app is a small, fully-owned React/Vite SPA with hand-written CSS
(`styles.css`, ~180 lines, one flat palette). shadcn/ui components are copied into the repo as
owned source (not an opaque npm dependency), which fits the existing pattern of small, readable,
directly-editable components (`SignalFilters.tsx`, `SignalTable.tsx`, `StatusStates.tsx`) and
avoids fighting a black-box theme to satisfy FR-009 (restyle filters/table/status surfaces
consistently). Tailwind's `dark` class strategy is the natural mechanism for FR-005..FR-008
(single toggle, applied everywhere, persisted, OS-default) — a `dark` class on `<html>` driven by
the new `ThemeProvider`, with CSS variables (already shadcn/ui convention) supplying the light/dark
palettes referenced from `styles.css`.

**Alternatives considered**:
- **Tremor** — rejected. Purpose-built for KPI cards, spark-lines, and date-range-picker-heavy
  analytics dashboards. Per the spec's Assumptions, this feature deliberately does not add new
  dashboard panels (KPI cards, positions/orders grids) beyond the existing Signal Viewer surface,
  so Tremor's core value proposition doesn't apply yet.

## Decision: No headless table library (TanStack Table / AG Grid)

**Rationale**: `SignalTable.tsx` sorting and pagination are already server-driven (the `sort` and
`limit`/`offset` query params on `GET /signals`, per the existing OpenAPI contract) — the frontend
does not currently do client-side sorting, filtering, or virtualization. FR-010 requires preserving
this behavior unchanged. Introducing a headless table library would add an abstraction with no
functional requirement driving it (violates the constitution's YAGNI clause under Development
Workflow). The existing table markup is restyled with Tailwind/shadcn `table` primitives instead.

**Alternatives considered**: TanStack Table (headless) and AG Grid — both rejected for now as
unjustified complexity given today's scope; revisit if a future feature adds client-side grid
behavior (multi-column client sort, inline editing, virtualized large grids).

## Decision: Theme persistence and default

**Rationale**: The application has no authentication (confirmed — no user/session model in the
existing API contract or backend), so FR-007 ("remember the user's theme") is scoped to
`localStorage` per device/browser rather than a server-synced account preference, matching the
spec's Assumptions. FR-008 (default to OS preference when nothing is stored) is implemented by
checking the `prefers-color-scheme` media query once, on first load with no stored key.

**Alternatives considered**: Account-level/server-synced preference — rejected as out of scope;
there is no account system to attach it to, and inventing one is far outside this feature's ask.

## Resolved unknown: testing a canvas-based chart under `jsdom`

**Problem**: `lightweight-charts` renders to `<canvas>`, which Vitest's `jsdom` test environment
(already configured in `vite.config.ts`) does not implement (`HTMLCanvasElement.getContext` is a
no-op stub in `jsdom`).

**Decision**: Follow `lightweight-charts`' own recommended test approach — mock the library's
`createChart` export in `CandlestickChart.test.tsx` (via `vi.mock('lightweight-charts', ...)`) and
assert against the mocked chart/series instance: that `addCandlestickSeries().setData(...)` is
called with the bars mapped to the library's `{ time, open, high, low, close }` shape, and that a
marker is set at the selected signal's date. This mirrors how the existing test suite already
avoids exercising real network calls (fixtures + mocked `api/client` in
`SignalsPage.test.tsx`/`fixtures.ts`) — the same "mock the boundary, assert on the call" pattern,
applied to a rendering boundary instead of a network boundary.

**Alternatives considered**: `canvas` npm package (native canvas polyfill for `jsdom`) — rejected;
adds a native-binary dependency and CI/Docker build complexity for no benefit beyond what mocking
the library boundary already achieves.

## Build integration note

Tailwind requires a `tailwind.config.ts` (with `darkMode: 'class'`) and `postcss.config.js`; Vite
picks up PostCSS config automatically, so no `vite.config.ts` plugin changes are needed beyond
adding the config files and updating `styles.css`'s `@tailwind` directives. This is confirmed
against the existing `vite.config.ts`, which has no PostCSS-incompatible custom pipeline.
