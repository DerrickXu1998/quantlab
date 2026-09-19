---

description: "Task list for Dockable Workspace"
---

# Tasks: Dockable Workspace

**Input**: Design documents from `/specs/004-dockable-workspace/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ui-contracts.md, quickstart.md

**Tests**: Included and REQUIRED — Constitution Principle IV (Test-First, NON-NEGOTIABLE) applies per
`plan.md`'s Constitution Check. Write each test, watch it fail, then implement.

**Organization**: Grouped by user story (spec.md priorities P1/P2/P3). All paths are relative to the
repository root (`frontend/...`); nothing is added under `quantlab_specs/` (Constitution: Repository
Structure).

**A note on how the phases divide.** Because docking comes from a library, the *ability* to
drag/split/tab arrives with the Foundational workspace host, not with US1. What US1 actually owns is
making rearranging **correct** — the chart resize seam (FR-009/SC-004), which `research.md` identifies
as the highest-risk part of this feature. The phases are drawn to reflect where the real work is.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1/US2/US3; Setup, Foundational, and Polish tasks carry no story label

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Bring in the docking library and the test seam it needs, without changing any UI yet.

- [X] T001 Add `dockview-react` (^8.3.1) to `frontend/package.json` dependencies and run `npm install`
      in `frontend/`. Install **`dockview-react`**, not `dockview` — per `research.md`, at v8 the
      `dockview` package is a pure re-export of the framework-agnostic core and contains no React
      component; `dockview-react` is where `DockviewReact` lives.
- [X] T002 [P] In `frontend/src/styles.css`, import the docking stylesheet
      (`dockview-react/dist/styles/dockview.css`) and add an override block mapping the `--dv-*`
      custom properties used by tab strips, borders, and drop indicators onto the existing app tokens
      (`--background`, `--card`, `--border`, `--foreground`, `--muted-foreground`, `--primary`), for
      both the `:root` and `.dark` cases (FR-012).
- [X] T003 [P] Create `frontend/tests/mocks/dockview-react.tsx`: a fake `DockviewReact` that renders
      each registered panel component directly and supplies a fake panel API whose
      `onDidDimensionsChange` / `onDidVisibilityChange` emitters and `width`/`height`/`isVisible`
      values tests can drive by hand. jsdom reports zero-sized boxes, so the real component cannot lay
      out — see `research.md`, "testing dockview under jsdom".
- [X] T004 Register the mock in `frontend/tests/setup.ts` via
      `vi.mock('dockview-react', async () => import('./mocks/dockview-react'))`, alongside the
      existing `lightweight-charts` mock (depends on: T003).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Stand up the workspace host and move shared state above the panels. Every user story is
blocked until panels render inside the dock.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 [P] Create `frontend/src/workspace/panels.tsx` implementing the Panel registry contract in
      `contracts/ui-contracts.md`: `PanelId = 'filters' | 'signals' | 'chart'`, each with a `title`
      and the existing feature component. Panel components MUST NOT import the docking library — that
      seam is what keeps them unit-testable and the library replaceable.
- [X] T006 [P] Create `frontend/src/workspace/defaultLayout.ts` exporting a single default-layout
      builder (filters, signal list, price chart in a sensible starting arrangement). This one builder
      backs both first-run layout and reset (FR-007) **and** the restore-failure fallback (FR-008), so
      those two paths can never drift apart.
- [X] T007 Lift all Signal Viewer state out of the panel components into a context provider in
      `frontend/src/workspace/WorkspaceContext.tsx`: `instruments`, `filters`, `page`, `signals`,
      `total`, `status`, `errorMessage`, `selected`, `contextBars`, and the three existing data-loading
      effects currently in `frontend/src/pages/SignalsPage.tsx`. **This is required, not stylistic**:
      dockview re-parents panel DOM when panels are dragged, which can remount panel components — state
      held inside a panel would be lost on every rearrange, violating FR-011/SC-007.
- [X] T008 Create `frontend/src/workspace/Workspace.tsx` implementing the Workspace host contract:
      renders `DockviewReact` with the `PANELS` registry, builds the default layout in `onReady`, and
      selects dock chrome theming from the existing `useTheme()` hook (light/dark theme objects
      exported by the library) so tabs, borders, and drop indicators follow the app theme (FR-012).
- [X] T009 Rewrite `frontend/src/pages/SignalsPage.tsx` to render `WorkspaceContext` + `Workspace`
      instead of the fixed filters → table → chart stack, keeping every existing data-loading behavior
      byte-for-byte identical (depends on: T007, T008).
- [X] T010 Update `frontend/src/App.tsx` so the workspace fills the viewport below the existing header
      (docking needs a bounded, full-height container), keeping the header and `ThemeToggle` from
      `003-modern-trading-ui` in place (depends on: T009).
- [X] T011 Run `npm test` in `frontend/` and confirm the existing `SignalsPage`, `SignalTable`,
      `SignalFilters`, `StatusStates`, `CandlestickChart`, `ThemeProvider`, and `ThemeToggle` suites
      still pass — the FR-010 regression guard. Fix any test-harness composition (e.g. wrapping in the
      new context provider) **without weakening any assertion** (depends on: T009, T010).

**Checkpoint**: Panels render inside the dock and can be dragged, split, and tabbed. The chart may
still mis-size on resize or tab-reveal — that is exactly what User Story 1 fixes.

---

## Phase 3: User Story 1 - Arrange the Workspace to Fit the Task (Priority: P1) 🎯 MVP

**Goal**: Make rearranging *correct* — above all, the chart must redraw at the right size on every
resize, move, float, and tab-reveal, never blank or zero-height (FR-009, SC-004).

**Independent Test**: Drag the chart beside the signal list, drag the divider, and stack the chart as
a background tab then reveal it — confirming the chart is correctly drawn in every case, and that
selection and loaded data survive rearranging — per `quickstart.md` §2.

### Tests for User Story 1 ⚠️

> Write these FIRST; confirm they FAIL before implementation (Constitution Principle IV).

- [X] T012 [P] [US1] Write `frontend/tests/usePanelSize.test.tsx` (must fail first) against the Panel
      size contract: returns initial `width`/`height`/`isVisible` on mount; updates when the fake
      `onDidDimensionsChange` emitter fires; reflects `isVisible: false` when the visibility emitter
      fires; unsubscribes from both emitters on unmount; and returns a sane default (rather than
      throwing) when rendered outside a dock panel.
- [X] T013 [P] [US1] Extend `frontend/tests/CandlestickChart.test.tsx` (must fail first): the chart
      calls the charting library's `resize(width, height)` when a **visible** panel's dimensions
      change; does **not** call it while `isVisible === false`; calls it **exactly once** on the
      hidden → visible transition; and does not remount or re-`setData` on resize (FR-009, FR-011).

### Implementation for User Story 1

- [X] T014 [US1] Create `frontend/src/components/usePanelSize.ts` per the Panel size contract:
      subscribe to the dock panel API's `onDidDimensionsChange` and `onDidVisibilityChange`, seed from
      `width`/`height`/`isVisible` on mount, unsubscribe on unmount, and degrade to a default when no
      panel API is present (depends on: T012 failing first).
- [X] T015 [US1] Modify `frontend/src/components/CandlestickChart.tsx`: remove `autoSize: true` from
      the chart options and drive sizing from `usePanelSize()` instead — call `chart.resize(width,
      height)` on change while visible, skip while hidden, and issue one resize on the transition back
      to visible. Do not remount the chart or re-send data on resize (depends on: T013 failing first,
      T014).
- [X] T016 [US1] Run `npm test` in `frontend/` and confirm `usePanelSize.test.tsx`,
      `CandlestickChart.test.tsx`, and all existing suites pass (depends on: T014, T015).
- [ ] T017 [US1] Manual pass of `quickstart.md` §2 — **especially step 7–8**, the background-tab
      reveal, which is the defect this story exists to prevent and which the mocked suite cannot prove
      (depends on: T016).

**Checkpoint**: The workspace can be rearranged and the chart is correct in every layout state — a
usable, demonstrable MVP even with no persistence.

---

## Phase 4: User Story 2 - Keep My Layout, and Get Back to Default (Priority: P2)

**Goal**: Persist the arrangement per browser, restore it on load, and always provide a reliable route
back to a working default (FR-005, FR-006, FR-007, FR-008).

**Independent Test**: Rearrange, reload and see the arrangement restored; reset and see the default
return; corrupt the stored layout and still land in a working workspace — per `quickstart.md` §3.

### Tests for User Story 2 ⚠️

> Write these FIRST; confirm they FAIL before implementation.

- [X] T018 [P] [US2] Write `frontend/tests/layoutStorage.test.ts` (must fail first) against the Layout
      store contract and `data-model.md`'s validation rules: `saveLayout`/`loadLayout` round-trips a
      layout with its `version` stamp; `loadLayout()` returns `null` — never throws — for an absent
      key, unparseable JSON, and a record whose `version` is missing or unknown; `clearLayout()`
      removes the key; and `saveLayout()` swallows storage failures (private mode / storage disabled)
      without throwing.
- [X] T019 [P] [US2] Write `frontend/tests/Workspace.test.tsx` (must fail first): every registered
      panel from `PANELS` renders; resetting rebuilds the default layout; a closed panel can be
      reopened (FR-005); and when applying a stored layout throws, the workspace falls back to the
      default rather than surfacing an error or rendering nothing (FR-008).

### Implementation for User Story 2

- [X] T020 [US2] Create `frontend/src/workspace/layoutStorage.ts` implementing the Layout store
      contract: `loadLayout()`, `saveLayout()`, `clearLayout()` over a dedicated `localStorage` key
      (e.g. `quantlab-workspace-layout`), storing `{ version, layout }`. Neither load nor save may
      throw (depends on: T018 failing first).
- [X] T021 [US2] Create `frontend/src/workspace/useWorkspaceLayout.ts`: on ready, apply a stored layout
      via `fromJSON` inside `try/catch`, and on **any** failure clear the workspace and rebuild from
      the `defaultLayout` builder (FR-008); subscribe to `onDidLayoutChange` and persist via
      **debounced** `saveLayout` — the event fires continuously during a divider drag, so an
      unthrottled write would hammer storage (depends on: T006, T020).
- [X] T022 [US2] Wire `useWorkspaceLayout` into `frontend/src/workspace/Workspace.tsx`, replacing the
      unconditional default-layout build from T008 (depends on: T021).
- [X] T023 [US2] Add a reset-layout control to the app shell in `frontend/src/App.tsx` that rebuilds
      the default arrangement immediately and overwrites the stored layout, with an accessible name
      (FR-007, SC-003) (depends on: T022).
- [X] T024 [US2] Add a control to reopen a closed panel in `frontend/src/workspace/Workspace.tsx`,
      listing registered panels not currently present, so closing a panel is recoverable without a full
      reset (FR-005) (depends on: T022).
- [ ] T025 [US2] Run `npm test`, then manually walk `quickstart.md` §3 — including both fallback
      cases (corrupt JSON and a layout referencing an unknown panel id) (depends on: T020–T024).

**Checkpoint**: Layouts survive reloads, and no arrangement or stored payload can strand the user.

---

## Phase 5: User Story 3 - Float a Panel Out of the Grid (Priority: P3)

**Goal**: Let a panel become a movable, resizable floating window and dock back again (FR-013).

**Independent Test**: Float the chart, move and resize it, dock it back, and reload with it floating —
per `quickstart.md` §4.

### Tests for User Story 3 ⚠️

- [X] T026 [P] [US3] Extend `frontend/tests/Workspace.test.tsx` (must fail first): invoking the float
      action calls the docking API's `addFloatingGroup` with the target panel, and the floating action
      is exposed with an accessible name rather than being drag-only (FR-013, FR-014).

### Implementation for User Story 3

- [X] T027 [US3] Add a float action to `frontend/src/workspace/Workspace.tsx` using the docking API's
      `addFloatingGroup(panel, options)`, reachable from the panel's tab context menu or header action
      (depends on: T026 failing first).
- [X] T028 [US3] Confirm floating panels round-trip through persistence — floating state, position, and
      size are part of the serialized layout, so verify `useWorkspaceLayout` restores them rather than
      dropping them to the grid (depends on: T021, T027).
- [ ] T029 [US3] Run `npm test`, then manually walk `quickstart.md` §4, including resizing a floating
      chart (the FR-009 seam applies to floating panels too) (depends on: T027, T028).

**Checkpoint**: All three stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T030 [P] Add a narrow-screen fallback in `frontend/src/workspace/Workspace.tsx`: below a usable
      docking width, render the panels as a simple stacked layout rather than presenting unusably small
      drag targets (spec Edge Cases; plan Constraints).
- [X] T031 [P] Accessibility pass for FR-014 in `frontend/src/workspace/Workspace.tsx` and
      `frontend/src/App.tsx`: every layout action essential to using the app (reset, reopen, float,
      close, switch tab) must be reachable and operable by keyboard with an accessible name — dragging
      may be an enhancement but never the only route.
- [X] T032 [P] Verify dock chrome theming end-to-end in both themes (tab strips, borders, drop
      indicators, floating frames) and tighten the `--dv-*` overrides in `frontend/src/styles.css` if
      any stock colors leak through (FR-012).
- [X] T033 [P] Update `docs/SIGNAL_VIEWER_DEMO.md` to describe the dockable workspace (rearrangeable
      panels, saved layouts, reset) instead of a fixed layout.
- [X] T034 Run `npm run lint`, `npx prettier --check .`, and `npm run build` in `frontend/`; fix any
      type or lint errors surfaced by the new modules.
- [X] T035 Run `docker build --target build ./frontend` to confirm the production image still builds
      with the new dependency (depends on: T034).
- [ ] T036 Full `quickstart.md` pass (§1–§7), including §7's contract checks: `frontend/src/api/
      schema.d.ts` unchanged, `backend/` untouched, and no panel content component importing the
      docking library (depends on: T034, T035).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS all three user stories** — nothing can be
  arranged, persisted, or floated until panels render inside the dock.
- **User Story 1 (Phase 3)**: Depends on Foundational. Independent of US2 and US3.
- **User Story 2 (Phase 4)**: Depends on Foundational. Independent of US1 — persistence neither reads
  nor writes chart sizing.
- **User Story 3 (Phase 5)**: Depends on Foundational; T028 also depends on US2's `useWorkspaceLayout`
  for the persistence round-trip. Floating itself does not depend on US1.
- **Polish (Phase 6)**: Depends on the stories being complete.

### User Story Dependencies

- **US1 (P1)**: No dependency on US2 or US3.
- **US2 (P2)**: No dependency on US1 or US3.
- **US3 (P3)**: One task (T028) depends on US2's persistence; the float action itself is independent.

### Within Each User Story

- Tests written and confirmed failing before implementation (Constitution Principle IV).
- Hook before consumer (US1: T014 before T015).
- Storage before the hook that uses it (US2: T020 before T021 before T022).
- Implementation before the manual quickstart pass.

### Parallel Opportunities

- T002, T003 in parallel (after T001).
- T005, T006 in parallel at the start of Foundational.
- Once Foundational completes, **US1, US2, and US3 can proceed in parallel** — US1 lives in
  `src/components/`, US2 in `src/workspace/layoutStorage.ts` + `useWorkspaceLayout.ts`, US3 in the
  float action. The one cross-story touch point is T028.
- Within US1: T012 and T013 in parallel. Within US2: T018 and T019 in parallel.
- Polish: T030, T031, T032, T033 in parallel.

---

## Parallel Example: Foundational → User Stories

```bash
# Start of Foundational:
Task: "Create panel registry in frontend/src/workspace/panels.tsx"
Task: "Create default layout builder in frontend/src/workspace/defaultLayout.ts"

# Once Foundational is done, three developers can split cleanly:
Developer A (US1): usePanelSize + CandlestickChart resize seam
Developer B (US2): layoutStorage + useWorkspaceLayout + reset/reopen controls
Developer C (US3): float action
```

---

## Implementation Strategy

### MVP First (Foundational + User Story 1)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1.
4. **STOP and VALIDATE**: `quickstart.md` §2, with real attention to the background-tab reveal.
5. Demo. A rearrangeable workspace with a correctly-rendering chart is genuinely useful even before
   layouts persist.

### Incremental Delivery

1. Setup + Foundational → panels live in the dock; nothing else changed for the user.
2. + US1 → rearranging is correct (MVP).
3. + US2 → layouts persist and are always recoverable.
4. + US3 → floating panels.
5. Polish → responsive fallback, keyboard access, theming, build and docs.

---

## Notes

- Tests are mandatory (Constitution Principle IV): write, watch fail, then implement.
- **The mocked suite does not prove the interactions.** Dragging, splitting, tabbing and floating are
  pointer-driven and the docking library is mocked under jsdom. A green test run is not evidence the
  workspace works — the `quickstart.md` manual passes (T017, T025, T029, T036) are.
- Panel content components must never import the docking library; that seam is enforced by the
  `grep` check in `quickstart.md` §7.
- All code lands under `frontend/`; nothing under `quantlab_specs/` (Constitution).
- No backend, OpenAPI contract, or `frontend/src/api/` changes anywhere in this list.

---

## Implementation Status Note (added by /speckit-implement)

Everything buildable is built: 66 tests pass (was 41), clean `tsc`, clean lint/prettier, Docker
image builds, and the contract checks in quickstart §7 all hold (`schema.d.ts` untouched, backend
untouched, no docking import in `src/components` or `src/pages`).

**Four tasks remain open because they are manual browser passes, and the docking library is mocked
under jsdom by design** (`research.md`). The suite proves the logic — persistence, fallback, resize
handling — not the pointer interactions. Still unverified by machine:

- **T017** (`quickstart.md` §2) — drag-to-split, divider resize, and above all the background-tab
  reveal: does the chart actually paint at full size, not blank or zero-height? (FR-009/SC-004)
- **T025** (`quickstart.md` §3) — layout survives reload; reset returns the default; a corrupt or
  outdated stored layout still lands in a working workspace
- **T029** (`quickstart.md` §4) — floating a panel, resizing it, docking it back
- **T036** (`quickstart.md` §1–§7) — full end-to-end pass

Stack is running for these: frontend http://localhost:5173, backend :8000 (933 seeded signals).
