# Phase 0 Research: Dockable Workspace

The Technical Context carried no `[NEEDS CLARIFICATION]` markers, but it did carry several claims that
would have been guesses. Every API fact below was verified by inspecting the published v8.3.1 typings
and stylesheets directly, not recalled. Corrections to the original framing are called out explicitly.

## Decision: use `dockview-react`, not `dockview`

**Correction to the request.** The feature was described as "Dockview — zero-dependency docking
manager". At v8, the package layout is not what that phrasing implies:

- `dockview-core@8.3.1` — the framework-agnostic engine. Verified: **zero** runtime dependencies, and
  no React bindings anywhere in its typings.
- `dockview@8.3.1` — verified to be a **pure re-export of `dockview-core`**. Its own source comment
  describes it as "a thin re-export"; it contains no React components.
- `dockview-react@8.3.1` — the React bindings (`DockviewReact` and friends). Depends on `dockview`,
  and declares `react`/`react-dom` `^16.8 || ^17 || ^18 || ^19` as **peer** dependencies.

**Decision**: install `dockview-react`. Installing `dockview` alone — the literal package named in the
request — would provide the engine but no React component, which would only surface as a confusing
failure at import time.

**The "zero-dependency" characterization survives in spirit**: the whole chain
(`dockview-react` → `dockview` → `dockview-core`) is first-party, and the engine pulls in no
third-party code. React is a peer dependency already satisfied by the project (18.3.1).

**Alternatives considered**: hand-rolled splitters (rejected — drag-to-split geometry, drop targets,
tab groups, floating windows and serialization are a large, bug-prone surface for no differentiating
value); full IDE-shell component kits (rejected — vastly more than this feature needs).

## Decision: fix the chart-sizing risk with dockview's own events, not ResizeObserver

This is the highest-risk item in the spec (FR-009 / SC-004) and the most likely way this feature
regresses `003-modern-trading-ui`.

**Problem**: `CandlestickChart` currently passes `autoSize: true` to `lightweight-charts`, which
installs a `ResizeObserver` on the chart container. Inside a docking workspace this breaks in two
well-known ways: a panel rendered in an **inactive tab** has a zero-sized (or detached) container, so
the chart initialises at zero height and stays blank when the tab is later revealed; and depending on
how a docking library hides panels, the observer may not fire at all on reveal.

**Decision**: stop relying on implicit observation. Verified to exist on dockview's panel API
(`IDockviewPanelProps.api`):

- `onDidDimensionsChange: Event<PanelDimensionChangeEvent>` — fires with new width/height on resize
- `onDidVisibilityChange: Event<VisibilityEvent>` — fires when a panel is hidden/revealed (tabbing)
- `isVisible`, `isActive`, `width`, `height` — current state, readable on mount

A `usePanelSize` hook subscribes to both events and returns `{ width, height, isVisible }`. The chart
drops `autoSize` and instead calls `chart.resize(width, height)` whenever those change, **skipping
the call while `isVisible` is false and issuing one resize on the transition back to visible**. This
turns an implicit, untestable browser behavior into explicit events that can be unit-tested with a
fake panel API — which is exactly why this is also the cheapest part of the feature to guard.

**Alternatives considered**: keeping `autoSize` and forcing a remount per visibility change (rejected
— throws away chart state and re-runs `setData` on every tab switch, and would violate SC-007's
"no extra work on rearrange" spirit); polling container size on an interval (rejected — wasteful and
still racy).

## Decision: layout persistence via `toJSON`/`fromJSON` with a guarded restore

**Verified API** on `DockviewApi`: `toJSON()`, `fromJSON(data)`, `clear()`, and the events
`onDidLayoutChange: Event<void>` and `onDidLayoutFromJSON: Event<void>`.

**Decision**: subscribe to `onDidLayoutChange`, serialize with `toJSON()`, and write to `localStorage`
**debounced** (a divider drag fires this event continuously; an unthrottled write would hammer storage
during a drag). On startup, read the stored layout and apply it with `fromJSON()` inside a `try/catch`;
on any failure, call `clear()` and build the default layout instead (FR-008). The same default-layout
builder backs the reset control (FR-007), so reset and fallback can never diverge.

**Rationale for the guard**: `fromJSON` is given data that may have been written by an older build of
the app, referencing panel ids that no longer exist. A `try/catch` plus rebuild is what keeps a stale
layout from turning into a blank workspace, which is the failure the spec explicitly forbids.

**Alternatives considered**: validating the serialized blob against a schema before applying
(rejected for now — dockview's serialized shape is an internal format and pinning a schema to it
would create a maintenance burden and false confidence; a `try/catch` around the real deserializer is
both simpler and more honest). A lightweight version stamp is kept alongside the blob so a future
breaking change can discard old layouts deliberately.

## Decision: theming through dockview's theme objects plus variable overrides

**Verified**: `dockview-core` exports ready-made theme objects including `themeLight` and `themeDark`
(among ~18 variants). The `DockviewTheme` interface carries `name`, `className`, and
`colorScheme?: 'light' | 'dark'`. The stylesheet ships at `dockview-react/dist/styles/dockview.css`
and defines ~115 `--dv-*` CSS custom properties.

**Decision**: import the stylesheet once, pass `theme={theme === 'dark' ? themeDark : themeLight}`
driven by the existing `useTheme()` hook from `003`, and override a small set of `--dv-*` variables in
`styles.css` so dock chrome (tab strips, borders, drop indicators) uses the app's existing token
palette rather than dockview's stock colors. This satisfies FR-012 without forking the stylesheet.

**Alternatives considered**: writing a bespoke dockview theme from scratch (rejected — ~115 variables
to own for cosmetic gain); leaving stock theming (rejected — visibly inconsistent with the design
delivered in `003`).

## Resolved unknown: testing dockview under `jsdom`

**Problem**: dockview computes layout from real element dimensions. Under `jsdom` every element
reports a zero-sized box, so a real `DockviewReact` renders no usable panel tree and assertions
against panel content would be testing nothing.

**Decision**: mock `dockview-react` at the module boundary in `tests/mocks/dockview-react.tsx`,
rendering registered panel components directly and exposing a fake panel API whose
dimension/visibility emitters tests can drive by hand. This reuses the pattern already established
for `lightweight-charts` in `003` and keeps the valuable logic testable as plain units:

- `layoutStorage` — save/load/clear, corrupt and outdated payloads (pure functions, no mock needed)
- `usePanelSize` — resize and hidden-tab transitions driven through the fake emitters
- `Workspace` — panel registry, reset-to-default, reopening a closed panel

**Consequence to state plainly**: as with the chart in `003`, mocking means the real drag-to-split,
tabbing and floating interactions are **not** machine-verified by this suite. Those are genuinely
pointer-driven behaviors; they belong to the manual pass in `quickstart.md`, and the plan should not
imply otherwise.

**Alternatives considered**: a real browser test runner (Playwright/Vitest browser mode) would
genuinely cover drag interactions — rejected for this feature as a disproportionate new CI
dependency, but it is the honest answer if docking interactions later need automated protection, and
is worth revisiting once the panel count grows.

## Note on scope, carried forward from the spec

The spec records that a docking manager is more machinery than three panels strictly need, and that
it only pays off if the product is genuinely heading toward a many-panel terminal. That judgment is
unchanged by this research and is recorded as a standing flag in the plan's Complexity Tracking table
rather than being quietly absorbed.
