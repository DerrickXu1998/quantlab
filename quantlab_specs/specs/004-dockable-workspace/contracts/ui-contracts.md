# UI Contracts: Dockable Workspace

This feature makes **no changes** to the backend-facing API contract. The REST contract in
`specs/002-signal-viewer-demo/contracts/openapi.yaml` is consumed exactly as today, and
`frontend/src/api/schema.d.ts` must come out of this feature byte-identical. What follows are the
**internal frontend contracts** this feature introduces, so implementation builds against stable
seams rather than reaching into the docking library from arbitrary components.

The organising rule: **panel content components must not import the docking library.** Everything
docking-specific lives behind the three contracts below. That is what keeps the existing component
tests valid, keeps panels unit-testable, and keeps a future library swap tractable.

## 1. Panel registry contract

```ts
export type PanelId = 'filters' | 'signals' | 'chart';

export interface PanelDefinition {
  id: PanelId;
  title: string;                          // shown on the tab
  component: React.FunctionComponent;     // an ordinary component; knows nothing about dockview
}

export const PANELS: Record<PanelId, PanelDefinition>;
```

- `PanelId` values are a **compatibility surface**: they are the only content identity stored inside
  a serialized layout. Renaming or removing one invalidates previously saved layouts, which the
  fallback in contract 2 must absorb (FR-008).
- Registration is data, not code branching — adding a fourth panel later is a new entry here plus a
  default-layout position, not a change to the workspace host.
- Every registered component must render correctly at arbitrary size, including very small, since
  panels are user-resizable.

## 2. Layout store contract

```ts
export interface StoredLayout {
  version: number;
  layout: SerializedDockview;   // opaque blob from DockviewApi.toJSON(); never inspected by this app
}

export function loadLayout(): StoredLayout | null;   // null when absent, unparseable, or wrong version
export function saveLayout(layout: SerializedDockview): void;
export function clearLayout(): void;
```

- `loadLayout()` **never throws**. Absent key, unparseable JSON, and unknown `version` all return
  `null`, meaning "use the default layout".
- `saveLayout()` never throws either — storage can be unavailable (private mode, disabled storage),
  and a failed write must not break the workspace, matching how theme persistence behaves in `003`.
- Callers must debounce `saveLayout()`; dockview's `onDidLayoutChange` fires continuously while a
  divider is dragged, and an unthrottled write per event would hammer storage during a drag.
- Applying a stored layout is guarded by the caller: `fromJSON()` inside `try/catch`, and on failure
  `clear()` the workspace and rebuild from the default. **Reset (FR-007) and restore-failure (FR-008)
  must call the same default-layout builder**, so the two paths can never drift apart.

## 3. Panel size contract (the FR-009 seam)

The contract that exists specifically to stop the chart rendering blank or zero-height.

```ts
export interface PanelSize {
  width: number;
  height: number;
  isVisible: boolean;
}

export function usePanelSize(): PanelSize;
```

- Backed by the panel API dockview passes to each panel component, using its verified events
  `onDidDimensionsChange` and `onDidVisibilityChange`, plus the initial `width`/`height`/`isVisible`
  readings on mount. It unsubscribes from both on unmount.
- Outside a dock panel (e.g. a component rendered standalone in a test or a narrow-screen fallback),
  it must return a sane default rather than throwing — panels have to stay renderable on their own.

**Required consumer behavior — `CandlestickChart`:**

- Stops passing `autoSize: true` to the charting library; container observation is replaced by these
  explicit events.
- Calls `chart.resize(width, height)` when a *visible* panel's dimensions change.
- **Does not** apply sizes while `isVisible === false` (an inactive tab has no meaningful box), and
  **applies one resize on the transition back to visible**. This transition is the exact defect
  FR-009/SC-004 exist to prevent and must be covered by a test.
- Does not remount or re-`setData` on resize or tab switching — rearranging must not re-fetch or
  reset state (FR-011, SC-007).

## 4. Workspace host contract

```ts
export interface WorkspaceProps {
  onResetLayout?: () => void;   // wired to the reset control in the app shell
}
```

- Hosts the docking component, registers `PANELS`, applies the stored or default layout on ready, and
  subscribes `onDidLayoutChange` → debounced `saveLayout`.
- Selects dock chrome theming from the existing `useTheme()` hook (light/dark theme objects), so dock
  tabs, borders and drop indicators follow the app theme (FR-012).
- Exposes reopening a closed panel (FR-005) and resetting to default (FR-007) without a page reload.
- Owns no domain state. Selection and fetched data continue to live above the panels so that
  rearranging never disturbs them (FR-011).

## Explicitly not part of this contract

- **No HTTP changes** — no new endpoints, params, or response fields; `schema.d.ts` unchanged.
- **No new panel types** (positions, orders, KPI tiles) — out of scope per the spec's Assumptions;
  adding one later is a `PANELS` entry, which is precisely why the registry is a contract.
- **No multi-chart comparison** — needs multi-selection semantics that do not exist today.
- **Popout/native browser windows** — dockview supports them, but the spec asks only for floating
  panels within the app (FR-013); popouts would add window-management and theming concerns not
  specified here.
