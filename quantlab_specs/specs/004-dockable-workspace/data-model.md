# Phase 1 Data Model: Dockable Workspace

This feature adds one new persisted client-side entity (Workspace Layout) and one in-memory registry
concept (Panel). No backend or database schema changes; the existing `Signal` and `PriceBar` entities
are untouched in shape and meaning.

## Workspace Layout (new — client-side only)

The saved arrangement of the workspace. Persisted per device/browser; there is no accounts system to
attach it to (consistent with how Theme Preference is handled in `003-modern-trading-ui`).

| Field | Type | Description |
|---|---|---|
| `version` | `number` | Stamp for the layout format. Lets a future breaking change discard incompatible saved layouts deliberately instead of relying on a deserialization failure. |
| `layout` | serialized dockview grid | The opaque arrangement blob produced by `DockviewApi.toJSON()`: panel positions, sizes, group/tab structure, active tab, and floating panel geometry. Treated as opaque — this app does not read inside it. |

**Storage**: a single `localStorage` key (e.g. `quantlab-workspace-layout`) holding the JSON of the
record above.

**Validation rules**:

- A missing key means "no saved layout" → build the default layout.
- Unparseable JSON, a missing/unknown `version`, or a `layout` that the deserializer rejects are all
  treated identically: **discard and fall back to the default layout** (FR-008). The workspace must
  always end up usable; a bad saved layout is never surfaced as an error state or a blank screen.
- The stored `layout` is never partially applied: on failure the workspace is cleared and rebuilt
  from the default, so the user cannot land in a half-restored arrangement.

**State transitions**:

```text
[no saved layout]      --(app load)-->            default layout built, nothing written yet
[any arrangement]      --(user rearranges)-->     onDidLayoutChange fires → debounced write
[saved layout present] --(app load, applies)-->   saved arrangement restored
[saved layout present] --(app load, rejected)-->  discarded → default layout built
[any arrangement]      --(user resets)-->         default layout rebuilt → saved layout overwritten
```

Writes are debounced: dragging a divider fires the change event continuously, and one storage write
per frame would be wasteful. The last state after a drag settles is what persists.

## Panel (new — in-memory registry concept)

One arrangeable region of the workspace. Panels are registered by a stable id; that id is the only
thing a serialized layout stores about content, so ids are a compatibility surface.

| Field | Type | Description |
|---|---|---|
| `id` | `'filters' \| 'signals' \| 'chart'` | Stable identifier. **Renaming or removing an id invalidates previously saved layouts referencing it** — which the FR-008 fallback is designed to absorb. |
| `title` | `string` | Human-readable label shown on the panel's tab. |
| `component` | React component | The existing feature component rendered inside the panel. |

**Validation rules**:

- Every panel id present in a restored layout must resolve to a registered component; unresolvable
  ids are what the FR-008 fallback catches.
- Panel components must not depend on the docking library, so they remain independently testable and
  the docking seam stays replaceable (see `contracts/ui-contracts.md`).

## Panel Size (new — transient, not persisted)

The current measured size and visibility of a panel, surfaced to content that must draw to exact
pixel dimensions (the chart). Derived from dockview's panel API events; deliberately **not** stored,
since it is recomputed from the live layout on every mount.

| Field | Type | Description |
|---|---|---|
| `width` | `number` | Current panel width in pixels. |
| `height` | `number` | Current panel height in pixels. |
| `isVisible` | `boolean` | Whether the panel is currently shown. False while it sits in an inactive tab — the case in which sizes must **not** be applied to the chart, because the container has no meaningful box. |

**State transitions that matter**:

```text
visible, resized        --> apply new size to chart
visible -> hidden       --> stop applying sizes (retain last known good size)
hidden  -> visible      --> apply current size once, so the chart is correct on reveal
```

That last transition is the specific defect FR-009 and SC-004 exist to prevent.

## Existing entities (unchanged)

- **Signal**, **Price Bar**, **Instrument** — unchanged in shape, source, and semantics; see
  `specs/002-signal-viewer-demo/contracts/openapi.yaml`. This feature changes only *where* the
  surfaces displaying them sit on screen.
- **Theme Preference** — unchanged, from `003-modern-trading-ui`. Consumed here to pick the dock
  chrome theme (FR-012), and stored under its own separate key; the two preferences are independent
  and neither read nor write the other.
