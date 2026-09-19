# UI Contracts: Modern Trading UI

This feature makes **no changes** to the backend-facing API contract. The existing REST contract
(`specs/002-signal-viewer-demo/contracts/openapi.yaml` — `GET /instruments`, `GET /signals`,
`GET /instruments/{symbol}/prices`) is consumed exactly as today; see that document for request/
response shapes. This file instead defines the new **internal frontend component contracts** this
feature introduces, so `/speckit-tasks` and implementation can build against a stable interface
rather than ad-hoc props.

## Theme contract

### `ThemeProvider`

Wraps the app (in `main.tsx` or `App.tsx`). Responsibilities per FR-005..FR-008:

- On mount, resolve the initial theme: read the `localStorage` theme key; if absent or invalid,
  fall back to `window.matchMedia('(prefers-color-scheme: dark)')`.
- Apply the resolved theme by toggling a `dark` class on the document root element (Tailwind's
  `darkMode: 'class'` strategy), so every Tailwind `dark:` utility and shadcn/ui CSS variable
  responds without prop drilling.
- Expose `useTheme()`.

### `useTheme()` hook contract

```ts
interface ThemeContextValue {
  theme: 'light' | 'dark';       // the currently resolved/applied theme
  setTheme: (theme: 'light' | 'dark') => void; // explicit set; persists to localStorage
  toggleTheme: () => void;       // convenience: flips light<->dark, persists to localStorage
}
```

- Calling `setTheme`/`toggleTheme` MUST update the DOM class synchronously (or on next paint) and
  write to `localStorage` — this is what makes source go from `system` to `stored` per
  `data-model.md`.
- Consumers (e.g. `ThemeToggle`) MUST NOT read/write `localStorage` directly; they go through this
  hook, keeping the persistence rule in one place.

### `ThemeToggle` component contract

- A single, always-visible, keyboard-operable control (button) rendered once in the app's shell
  (e.g. a header), not per-page — satisfies FR-005 ("single, always-accessible control").
- Props: none required (reads/writes via `useTheme()`); accepts standard HTML button attributes
  for placement/styling only.
- Accessible name communicates the action ("Switch to dark mode" / "Switch to light mode"), not a
  static label — satisfies FR-012 (keyboard/contrast/accessibility).

## Chart contract

### `CandlestickChart` (replaces `PriceChart`)

```ts
interface CandlestickChartProps {
  bars: PriceBar[];        // existing type from ../api/client — unchanged shape
  markerDate?: string;     // existing prop name/semantics, carried over from PriceChart
}
```

- Same prop shape as today's `PriceChart` (`bars`, `markerDate`) — this is a drop-in replacement
  at the call site in `SignalsPage.tsx`; no changes needed to how the page fetches or passes data.
- Renders an OHLC candlestick series from `bars` (mapping `date→time`, `open`, `high`, `low`,
  `close`), plus a volume series/pane from `bars[].volume` (FR-001, FR-003).
- When `bars` is empty, renders the same "no data" state contract as today (`chart-empty`
  equivalent), restyled for both themes — satisfies the "no price history" edge case.
- When `markerDate` is provided and matches a bar, places a visual marker on that bar equivalent
  to today's red dashed line + dot (FR-004).
- MUST read the current theme (via `useTheme()`) to pick the chart's background/grid/candle
  colors, so it repaints correctly on theme toggle without a remount (part of FR-006's "applied
  consistently across every component").
- Internally responsible for chart instance lifecycle (create on mount, `setData` on `bars`
  change, `remove()` on unmount) — this lifecycle is what `ThemeProvider.test.tsx`/
  `CandlestickChart.test.tsx` mock against (see `research.md`'s resolved `jsdom` testing note).

## Explicitly not part of this contract

- No new HTTP endpoints, query params, or response fields — reuses `specs/002-signal-viewer-demo/
  contracts/openapi.yaml` unchanged.
- No indicator-overlay props (e.g. moving-average series) on `CandlestickChart` — out of scope
  per the spec's Assumptions; adding them later would be an additive, non-breaking prop change.
