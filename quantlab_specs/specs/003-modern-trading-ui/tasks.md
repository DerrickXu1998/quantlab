---

description: "Task list for Modern Trading UI"
---

# Tasks: Modern Trading UI

**Input**: Design documents from `/specs/003-modern-trading-ui/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/ui-contracts.md, quickstart.md

**Tests**: Included and REQUIRED — Constitution Principle IV (Test-First, NON-NEGOTIABLE) applies to
this feature per `plan.md`'s Constitution Check: new components get tests written first, shown to
fail, then implemented.

**Organization**: Tasks are grouped by user story (from `spec.md`, priorities P1/P2/P3) to enable
independent implementation and testing of each story. All paths are relative to the repository
root (`frontend/...`), per `plan.md`'s Project Structure — no files are added under
`quantlab_specs/` (Constitution: Repository Structure).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3); Setup/Foundational/Polish
  tasks carry no story label

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Bring in the Tailwind + shadcn/ui toolchain this whole feature builds on (per
`research.md`'s "Dashboard shell" decision), without touching any component behavior yet.

- [X] T001 Add new dependencies to `frontend/package.json` and install: `lightweight-charts`,
      `tailwindcss`, `postcss`, `autoprefixer`, `class-variance-authority`, `clsx`,
      `tailwind-merge`, `tailwindcss-animate`, `@radix-ui/react-slot` (run `npm install` in
      `frontend/`)
- [X] T002 [P] Create `frontend/tailwind.config.ts`: `darkMode: 'class'` (required for
      `ThemeProvider`'s class-toggle strategy per `contracts/ui-contracts.md`), `content` globbing
      `./index.html` and `./src/**/*.{ts,tsx}`, theme tokens extended via CSS variables
- [X] T003 [P] Create `frontend/postcss.config.js` wiring the `tailwindcss` and `autoprefixer`
      plugins (Vite picks this up automatically — no `vite.config.ts` change needed, per
      `research.md`'s build integration note)
- [X] T004 Rewrite `frontend/src/styles.css` as the Tailwind entry point: `@tailwind base;`,
      `@tailwind components;`, `@tailwind utilities;`, plus a `:root { ... }` block and a
      `.dark { ... }` block defining the light/dark color tokens (background, foreground, border,
      accent, destructive, etc.) that every `src/components/ui/*` primitive and
      `CandlestickChart`'s theme-aware colors will read
- [X] T005 [P] Add `frontend/src/lib/utils.ts` exporting `cn()` (via `clsx` + `tailwind-merge`),
      the shared classname helper used by every component under `frontend/src/components/ui/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The theme engine. `CandlestickChart` (US1) reads it for chart colors and
`ThemeToggle` (US2) reads/writes it — both stories are blocked until this exists.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 [P] Write `frontend/tests/ThemeProvider.test.tsx` (must fail first): with no stored
      preference and `prefers-color-scheme: dark`, initial `theme` is `'dark'`; with no stored
      preference and `prefers-color-scheme: light`, initial `theme` is `'light'`; calling
      `setTheme`/`toggleTheme` adds/removes the `dark` class on `document.documentElement` and
      writes the value to the `localStorage` theme key; a stored value wins over the system
      preference on the next mount; an invalid/corrupt stored value falls back to the system
      preference instead of throwing — per `data-model.md`'s Theme Preference validation rules and
      state-transition table
- [X] T007 Implement `frontend/src/theme/ThemeProvider.tsx` (the provider component) and its
      `useTheme()` hook per `contracts/ui-contracts.md`'s Theme contract: resolve the initial theme
      (stored `localStorage` key, else `window.matchMedia('(prefers-color-scheme: dark)')`), apply
      it by toggling the `dark` class on the document root, and expose
      `{ theme, setTheme, toggleTheme }`, persisting every change to `localStorage` (depends on:
      T006 failing first)
- [X] T008 Wrap the app with `ThemeProvider` in `frontend/src/main.tsx`, so `useTheme()` is
      available to every component in every story (depends on: T007)

**Checkpoint**: Foundation ready — User Story 1 and User Story 2 implementation can now begin (in
parallel, if staffed).

---

## Phase 3: User Story 1 - Read Price Action on a Real Candlestick Chart (Priority: P1) 🎯 MVP

**Goal**: Replace the closing-price-only SVG line (`frontend/src/components/PriceChart.tsx`) with
a real OHLC candlestick chart that supports pan/zoom, a hover readout, and the existing
signal-date marker (FR-001–FR-004, FR-011).

**Independent Test**: Select any signal with price history; confirm the panel renders distinct
up/down candles (not a line), a hover readout with exact OHLCV values, smooth pan/zoom across the
full history, and the selected signal's date still marked — per `quickstart.md` §2.

### Tests for User Story 1 ⚠️

> Write these tests FIRST; confirm they FAIL before implementation (Constitution Principle IV).

- [X] T009 [P] [US1] Add a shared `lightweight-charts` mock at
      `frontend/tests/mocks/lightweight-charts.ts` (fake `createChart` returning fake chart/series
      objects with `vi.fn()` for `setData`, `setMarkers`, `remove`, etc. — per `research.md`'s
      resolved "testing a canvas-based chart under `jsdom`" note) and register it globally via
      `vi.mock('lightweight-charts', ...)` in `frontend/tests/setup.ts`, so any test that mounts a
      chart (including `SignalsPage.test.tsx`) runs safely under `jsdom`
- [X] T010 [P] [US1] Write `frontend/tests/CandlestickChart.test.tsx` (must fail first): bars are
      mapped to `{ time, open, high, low, close }` and passed to the candlestick series'
      `setData`; `bars[].volume` is passed to a volume series/pane; `setMarkers` is called with
      the bar matching `markerDate`; the container carries `data-testid="price-chart"`; a
      `data-testid="signal-marker"` element is present only when `markerDate` matches a bar; an
      empty `bars` array renders a "no data" message instead of mounting the chart — per
      `contracts/ui-contracts.md`'s Chart contract

### Implementation for User Story 1

- [X] T011 [US1] Create `frontend/src/components/CandlestickChart.tsx` per
      `contracts/ui-contracts.md`: props `{ bars: PriceBar[]; markerDate?: string }`; on mount,
      create the chart into a container div carrying `data-testid="price-chart"`, add a
      candlestick series (`setData` from mapped bars) and a volume series (`setData` from
      `bars[].volume`); re-call `setData`/`setMarkers` when `bars`/`markerDate` change; call
      `chart.remove()` on unmount; when `bars.length === 0`, render the same "No price history
      available." message the current `PriceChart` shows; when `markerDate` matches a bar, also
      render a visually-hidden element with `data-testid="signal-marker"` and the marker date as
      accessible text (an accessible, DOM-visible equivalent of the canvas-drawn marker — keeps
      `frontend/tests/SignalsPage.test.tsx:74-75`'s existing assertions passing unmodified and
      satisfies FR-012 for screen-reader users, since a canvas marker alone is not perceivable);
      read `theme` via `useTheme()` and pass matching background/grid/candle colors into the chart
      options so it repaints on toggle without remounting (depends on: T007, T009, T010 failing
      first)
- [X] T012 [US1] Replace `PriceChart` with `CandlestickChart` at its one call site in
      `frontend/src/pages/SignalsPage.tsx` (same props: `bars={contextBars}
      markerDate={selected.date}`) (depends on: T011)
- [X] T013 [P] [US1] Delete `frontend/src/components/PriceChart.tsx` and remove its now-unused
      `.price-chart` / `.chart-axis-label` rules from `frontend/src/styles.css` (depends on: T012)
- [X] T014 [US1] Run `npm test` in `frontend/` and confirm `ThemeProvider.test.tsx`,
      `CandlestickChart.test.tsx`, and the existing `SignalsPage.test.tsx` price-chart/
      signal-marker assertions all pass against the new component, unmodified (depends on: T011,
      T012, T013)

**Checkpoint**: User Story 1 is fully functional and independently testable — selecting a signal
shows a real candlestick chart with pan/zoom, hover readout, and its marker.

---

## Phase 4: User Story 2 - Switch Between Dark Mode and Light Mode (Priority: P2)

**Goal**: A single, always-visible control that switches the whole app between light and dark
instantly, defaults to the OS preference, and persists per browser (FR-005–FR-008).

**Independent Test**: Toggle the theme control; confirm every visible surface switches
immediately with no reload, and that reopening the app later restores the same choice — per
`quickstart.md` §3. Independently testable even before User Story 3's restyle ships, since the
theme engine (Phase 2) already applies to whatever is on screen.

### Tests for User Story 2 ⚠️

> Write these tests FIRST; confirm they FAIL before implementation (Constitution Principle IV).

- [X] T015 [P] [US2] Write `frontend/tests/ThemeToggle.test.tsx` (must fail first): renders a
      single keyboard-operable button whose accessible name describes the action ("Switch to dark
      mode" / "Switch to light mode"); activating it calls `toggleTheme` from `ThemeProvider`; its
      accessible name flips after the theme changes — per `contracts/ui-contracts.md`'s
      `ThemeToggle` contract and FR-012

### Implementation for User Story 2

- [X] T016 [P] [US2] Copy in a minimal shadcn/ui `Button` primitive at
      `frontend/src/components/ui/button.tsx` (`class-variance-authority`-based variants, built on
      `cn()` from T005), used by `ThemeToggle`
- [X] T017 [US2] Implement `frontend/src/theme/ThemeToggle.tsx` per
      `contracts/ui-contracts.md`: renders the `Button` primitive, reads `{ theme, toggleTheme }`
      via `useTheme()`, sets an accessible name describing the action it performs, shows a
      light/dark icon affordance (depends on: T007, T015 failing first, T016)
- [X] T018 [US2] Render `ThemeToggle` once in the app shell (e.g. a header) in
      `frontend/src/App.tsx` — not per-page, per FR-005's "single, always-accessible control"
      (depends on: T017)
- [X] T019 [US2] Run `npm test` and confirm `ThemeToggle.test.tsx` passes; walk through
      `quickstart.md` §3 manually to confirm first-load theme matches the OS preference and that
      toggling repaints the User Story 1 chart's colors without remounting it (depends on: T011's
      theme-aware colors, T017, T018)

**Checkpoint**: User Stories 1 and 2 both work independently — the candlestick chart renders
correctly in either theme, and the toggle switches the whole app instantly and remembers the
choice.

---

## Phase 5: User Story 3 - Browse a Modernized, Consistent Dashboard (Priority: P3)

**Goal**: Restyle the filters panel, signal table, and status messages to match the new look in
both themes, with zero change to existing filter/sort/pagination/selection behavior (FR-009,
FR-010, FR-013).

**Independent Test**: Perform every existing workflow (filter, sort, page, select a signal)
against the restyled interface and confirm identical results to today, at both desktop and
tablet widths — per `quickstart.md` §4. Independently verifiable via the existing, unmodified
`SignalFilters.test.tsx` / `SignalTable.test.tsx` / `StatusStates.test.tsx` / `SignalsPage.test.tsx`
suites, which act as the regression guard for this story.

### Tests for User Story 3 ⚠️

> The existing test suites already assert current behavior and serve as the regression guard
> (FR-010) for this story's restyle. Add the one new assertion below first; confirm it fails
> before the restyle.

- [X] T020 [P] [US3] Add an assertion to `frontend/tests/StatusStates.test.tsx` confirming
      `Loading`, `EmptyResults`, and `BackendUnavailable` keep their existing `role`/
      `data-testid` attributes after restyling (must fail first if the restyle has not yet
      touched these components' markup)

### Implementation for User Story 3

- [X] T021 [P] [US3] Copy in shadcn/ui `Table` and `Card` primitives at
      `frontend/src/components/ui/table.tsx` and `frontend/src/components/ui/card.tsx` (used by
      `SignalTable` and the signal-context panel)
- [X] T022 [P] [US3] Copy in shadcn/ui `Input`, `Label`, and `Select` primitives at
      `frontend/src/components/ui/input.tsx`, `frontend/src/components/ui/label.tsx`, and
      `frontend/src/components/ui/select.tsx` (used by `SignalFilters`' instrument/type/date/
      direction controls)
- [X] T023 [US3] Restyle `frontend/src/components/SignalFilters.tsx` with the new `ui/`
      primitives, keeping its existing props (`instruments`, `value`, `onChange`) and filter
      behavior identical (depends on: T022)
- [X] T024 [US3] Restyle `frontend/src/components/SignalTable.tsx` with the new `ui/` `Table`
      primitive, keeping its existing props (`signals`, `total`, `selectedId`, `page`, `pageSize`,
      `onPageChange`, `onSelect`) and sort/pagination behavior identical (depends on: T021)
- [X] T025 [US3] Restyle `frontend/src/components/StatusStates.tsx` (`Loading`, `EmptyResults`,
      `BackendUnavailable`) to the new visual design in both themes, keeping existing `role`/
      `data-testid` attributes (depends on: T021, T020 failing first)
- [X] T026 [US3] Restyle the page shell and signal-context panel in
      `frontend/src/pages/SignalsPage.tsx` (layout, headings, spacing) using the `Card` primitive,
      keeping all existing state and behavior unchanged (depends on: T021, T023, T024, T025)
- [X] T027 [US3] Run `npm test`, `npm run lint`, and `npm run format:check` in `frontend/` and
      confirm `SignalFilters.test.tsx`, `SignalTable.test.tsx`, `StatusStates.test.tsx`, and
      `SignalsPage.test.tsx` all still pass — the regression guard for FR-010 (depends on: T020,
      T023, T024, T025, T026)
- [ ] T028 [US3] Manually walk through `quickstart.md` §4 (filter/sort/page/select parity, and
      tablet-width layout with no overlapping or clipped elements — FR-013) (depends on: T027)

**Checkpoint**: All three user stories are independently functional — a fully modernized,
themeable Signal Viewer with zero behavioral regressions.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final build/deploy confirmation and full-stack validation, per `quickstart.md`.

- [X] T029 [P] Check `docs/SIGNAL_VIEWER_DEMO.md` and the root `README.md` for outdated
      descriptions/screenshots of the old plain-line-chart look and update them if present
- [X] T030 [P] Run `npm run build` (`tsc && vite build`) in `frontend/` and fix any type errors
      surfaced by the new components
- [X] T031 Run the production Docker build (`docker build --target build ./frontend`, or `make
      docker-shell`) to confirm the image still builds and serves, per `quickstart.md` §5
- [ ] T032 Run `quickstart.md`'s full validation pass (§1–§6) end-to-end against `make up`, and
      confirm §6's contract sanity checks: `frontend/src/api/schema.d.ts` is unchanged, and no new
      files were added under `quantlab_specs/` outside this feature's own docs

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup (T004's CSS tokens exist for `ThemeProvider` to
  toggle). BLOCKS User Story 1 and User Story 2.
- **User Story 1 (Phase 3)**: Depends on Foundational (T007's `useTheme()`). Independent of User
  Story 2 and User Story 3.
- **User Story 2 (Phase 4)**: Depends on Foundational (T007). Independent of User Story 1's
  chart — only reuses it for a manual repaint check in T019. Independent of User Story 3.
- **User Story 3 (Phase 5)**: Depends on Setup only (T005's `cn()`), not on User Story 1 or 2 — it
  restyles components untouched by either. Can proceed in parallel with Phase 3/4 once Setup is
  done, though it shares no files with them.
- **Polish (Phase 6)**: Depends on all three user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: No dependency on US2 or US3.
- **User Story 2 (P2)**: No dependency on US1 or US3 (T019's manual check is a verification step,
  not a build dependency).
- **User Story 3 (P3)**: No dependency on US1 or US2.

### Within Each User Story

- Tests written and confirmed failing before implementation (Constitution Principle IV).
- `CandlestickChart`/`ThemeToggle` component before wiring it into a page (US1: T011 before T012;
  US2: T017 before T018).
- Restyle tasks before the final regression-suite run (US3: T023–T026 before T027).

### Parallel Opportunities

- T002, T003, T005 (Setup) can run in parallel with each other (and after T001).
- T006 (Foundational test) can be written in parallel with Setup tasks, but T007 needs T006
  failing first and T004's tokens in place.
- Once Foundational (Phase 2) is done: **User Story 1, User Story 2, and User Story 3 can all
  proceed in parallel** (different files: `CandlestickChart.tsx`/`PriceChart.tsx` vs.
  `ThemeToggle.tsx`/`App.tsx` vs. `SignalFilters.tsx`/`SignalTable.tsx`/`StatusStates.tsx`).
- Within US1: T009 and T010 in parallel; T013 in parallel with T014.
- Within US2: T015 and T016 in parallel.
- Within US3: T020, T021, T022 in parallel.

---

## Parallel Example: User Story 1

```bash
# Tests (after Foundational is done):
Task: "Add shared lightweight-charts mock in frontend/tests/mocks/lightweight-charts.ts + wire into tests/setup.ts"
Task: "Write frontend/tests/CandlestickChart.test.tsx"

# Cleanup, once T012 lands:
Task: "Delete frontend/src/components/PriceChart.tsx and its unused CSS rules"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (blocks everything else).
3. Complete Phase 3: User Story 1 — the candlestick chart, the most visible fix for the "out of
   date" complaint.
4. **STOP and VALIDATE**: run `quickstart.md` §2 against the MVP.
5. Demo if ready — dark/light mode (US2) and the full restyle (US3) can ship as fast-follow
   increments without touching US1's files.

### Incremental Delivery

1. Setup + Foundational → theme engine ready, nothing visibly changed yet.
2. Add User Story 1 → validate via `quickstart.md` §2 → demo (MVP: real candlestick chart).
3. Add User Story 2 → validate via `quickstart.md` §3 → demo (dark/light toggle everywhere).
4. Add User Story 3 → validate via `quickstart.md` §4 → demo (fully modernized shell).
5. Phase 6 → validate via `quickstart.md` §1, §5, §6 → build/deploy confirmed, ship.

### Parallel Team Strategy

With multiple developers, once Foundational is done: Developer A takes US1 (chart), Developer B
takes US2 (theme toggle), Developer C takes US3 (shell restyle) — none share a file, so they
integrate without conflict.

---

## Notes

- [P] tasks touch different files with no unfinished dependency between them.
- Tests are mandatory here (Constitution Principle IV) — write each test, watch it fail, then
  implement.
- Every task's file path is exact; no task should require guessing a location.
- All implementation code lands under `frontend/` at the repository root — nothing under
  `quantlab_specs/` (Constitution: Repository Structure).
- No backend, OpenAPI contract, or `frontend/src/api/` changes anywhere in this task list — this
  feature is frontend-only, per `plan.md`.

---

## Implementation Status Note (added by /speckit-implement)

T028 and T032 are the two manual, in-browser passes. Everything they depend on is built,
type-checks, lints, builds in Docker, and is covered by 41 passing tests — but the real
`lightweight-charts` canvas render path is mocked under jsdom by design, so the visual
behaviors below have NOT been machine-verified and need a human pass at
http://localhost:5173 (backend already seeded on :8000):

- Candles actually paint (not a blank canvas), pan/zoom is smooth — FR-001, FR-002, FR-011
- Hover readout shows the right OHLCV for the hovered bar — FR-003
- The signal marker lands on the correct bar — FR-004
- Toggling theme repaints chart colors without remounting — FR-006
- Tablet-width layout has no overlap/clipping — FR-013
