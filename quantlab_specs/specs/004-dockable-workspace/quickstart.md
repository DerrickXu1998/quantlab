# Quickstart: Validating the Dockable Workspace

Prerequisites: Node.js per `frontend/package.json`, and the backend running so panels have real data.

> **Read this first.** Drag-to-split, tabbing and floating are pointer-driven behaviors, and the
> automated suite mocks the docking library under `jsdom` (see `research.md`). The automated checks in
> §6 prove the *logic* — persistence, fallback, resize handling — not the *interactions*. Sections
> §2–§5 are a genuine manual pass and are the only thing that verifies the feature works.

## 1. Run the app

```sh
# from repository root — full stack
make up

# OR, frontend only against an already-running backend on :8000
cd frontend
npm install
npm run dev
```

## 2. Validate User Story 1 — arranging the workspace (P1)

1. Drag the chart panel's tab to the right edge of the signal list panel.
2. **Expect**: the two panels sit side by side, both fully interactive — validates FR-002.
3. Drag the divider between them left and right.
4. **Expect**: both panels resize smoothly, and **the chart redraws to fill its new width with no
   blank, clipped, or stretched rendering** — validates FR-003, FR-009, SC-004.
5. Drag one panel onto another panel's tab strip.
6. **Expect**: they become a tabbed group; clicking tabs switches between them — validates FR-004.
7. **Now the critical case**: with the chart stacked as a *background* tab, switch away from it, then
   click its tab to reveal it.
8. **Expect**: the chart is drawn at full correct size immediately on reveal — **not** blank, and not
   a thin zero-height strip. This is the single most likely regression in this feature — validates
   FR-009, SC-004.
9. Select a signal, then rearrange panels.
10. **Expect**: the selection and loaded data survive; the network tab shows **no new requests**
    caused by rearranging — validates FR-011, SC-007.
11. Close a panel, then reopen it from the reopen control.
12. **Expect**: it returns with working content — validates FR-005.

## 3. Validate User Story 2 — persistence and reset (P2)

1. Arrange the workspace distinctively (e.g. chart left, list right, filters tabbed).
2. Reload the page.
3. **Expect**: your arrangement is restored — positions, sizes, tab grouping, and which tab was
   active — validates FR-006, SC-002.
4. Activate the reset control.
5. **Expect**: the default arrangement returns immediately — validates FR-007, SC-003.
6. **Corrupt-layout fallback**: in devtools, set the workspace layout key to junk:
   ```js
   localStorage.setItem('quantlab-workspace-layout', '{not valid json');
   ```
   then reload.
7. **Expect**: a working default workspace, with no error screen and no blank page — validates
   FR-008, SC-006.
8. **Outdated-layout fallback**: set the key to a structurally valid layout referencing an unknown
   panel id, then reload.
9. **Expect**: same graceful fallback to a usable workspace — validates FR-008.

## 4. Validate User Story 3 — floating panels (P3)

1. Float the chart panel out of the grid.
2. **Expect**: a movable, resizable window above the workspace; the chart stays interactive —
   validates FR-013.
3. Resize the floating window.
4. **Expect**: the chart redraws correctly at the new size — validates FR-009.
5. Drag it back into the grid; reload with a floating panel open.
6. **Expect**: it docks back cleanly, and floating state/position/size survives reload — validates
   FR-013 and the floating clause of FR-006.

## 5. Cross-cutting checks

1. Toggle light/dark mode with panels arranged and tabbed.
2. **Expect**: dock chrome — tab strips, borders, drag indicators, floating frames — follows the
   theme, with no leftover light-themed chrome in dark mode, and the chart repaints — validates
   FR-012.
3. Tab through the app with the keyboard only.
4. **Expect**: panels and their controls remain reachable and operable; nothing essential is reachable
   only by dragging — validates FR-014.
5. Narrow the window to tablet width.
6. **Expect**: the workspace stays readable and usable rather than presenting unusably small drag
   targets.
7. Exercise every existing workflow: filter by instrument/type/direction/date, sort, page, select
   rows.
8. **Expect**: identical results to before this feature — validates FR-010, SC-005.

## 6. Automated checks

```sh
cd frontend
npm run lint
npm run format:check
npm run build          # tsc && vite build
npm test               # vitest run
```

The suite must include, and keep passing:

- `layoutStorage.test.ts` — save/load round-trip; absent, unparseable, and wrong-version payloads all
  fall back to "no layout" without throwing (FR-006, FR-008)
- `usePanelSize.test.tsx` — resize while visible applies; changes while hidden do not; the
  hidden → visible transition applies exactly one resize (FR-009)
- `Workspace.test.tsx` — panel registry renders each registered panel; reset rebuilds the default;
  a closed panel can be reopened (FR-005, FR-007)
- the existing `SignalsPage` / `SignalTable` / `SignalFilters` / `StatusStates` / `CandlestickChart` /
  `ThemeProvider` / `ThemeToggle` suites — unchanged, as the FR-010 regression guard

## 7. Contract sanity checks

```sh
git diff --stat -- frontend/src/api/schema.d.ts    # must be empty
git status --short -- backend src tests            # must be empty
```

- `frontend/src/api/schema.d.ts` unchanged — this feature makes no backend changes.
- No files added under `quantlab_specs/` beyond this feature's own documents (Constitution:
  Repository Structure).
- Confirm no panel content component imports the docking library directly:
  ```sh
  grep -rn "dockview" frontend/src/components frontend/src/pages || echo "clean — docking stays behind src/workspace/"
  ```
