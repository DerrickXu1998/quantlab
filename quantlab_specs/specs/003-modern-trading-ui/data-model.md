# Phase 1 Data Model: Modern Trading UI

This feature adds one new client-side concept (Theme Preference) and changes how two existing,
backend-owned entities are *displayed* without changing their shape. There is no backend or
database schema change.

## Theme Preference (new — client-side only)

Not persisted server-side; there is no accounts/session system to attach it to (see spec
Assumptions). Lives entirely in the browser.

| Field | Type | Description |
|---|---|---|
| `theme` | `'light' \| 'dark'` | The resolved, currently-applied theme. |
| `source` | `'stored' \| 'system'` | Whether `theme` came from a saved preference or was derived from the OS/browser's `prefers-color-scheme`. Not persisted — recomputed each load. |

**Storage**: a single `localStorage` key (e.g. `quantlab-theme`) holding `'light'` or `'dark'`.
Absent key ⇒ `source: 'system'`, resolved from `prefers-color-scheme`; present key ⇒
`source: 'stored'`, resolved from the stored value (FR-007, FR-008).

**Validation rules**: only `'light'` or `'dark'` are valid values; any other/corrupt stored value
is treated as absent (falls back to system preference) rather than causing an error, consistent
with the constitution's "degrade gracefully" spirit (Principle II) applied here to a UI concern.

**State transitions**:

```text
[no stored key] --(OS reports dark)--> theme=dark, source=system
[no stored key] --(OS reports light)--> theme=light, source=system
[any state] --(user activates toggle)--> theme=<other value>, source=stored, localStorage written
[stored key present] --(app load)--> theme=<stored value>, source=stored
```

There is no transition back to `source: system` once a user has toggled — this matches FR-007
("remember the user's theme... restore it on the next visit") and the edge case in the spec that
the app does not need to react live to OS changes mid-session once a preference exists.

## Price Bar (existing — display change only)

Unchanged shape, sourced from the existing `PriceBar` schema in
`specs/002-signal-viewer-demo/contracts/openapi.yaml` (`symbol`, `date`, `open`, `high`, `low`,
`close`, `volume`). This feature changes only how all five OHLCV fields are visualized (candlestick
instead of a `close`-only line, per FR-001) — no field is added, removed, or reinterpreted.

## Signal (existing — unchanged)

Unchanged shape and unchanged semantics, sourced from the existing `Signal` schema in the same
OpenAPI contract. This feature only changes how the selected signal's date is marked on the
(now-candlestick) chart (FR-004) and how signal rows are styled in the table (FR-009) — no field,
filter, sort key, or pagination behavior changes (FR-010).
