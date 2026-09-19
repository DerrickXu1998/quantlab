# Quickstart: Validating the Modern Trading UI

Prerequisites: Node.js (per `frontend/package.json` toolchain), the backend stack running so the
frontend has real data to render (`make up` from the repository root — seeds the demo DB, starts
`backend`, then `frontend`; see `docker-compose.yml`).

## 1. Run the app

```sh
# from repository root — full stack (matches how the feature will actually be demoed)
make up

# OR, frontend only against an already-running backend on :8000
cd frontend
npm install
npm run dev
```

Open the printed local URL.

## 2. Validate User Story 1 — candlestick chart (P1)

1. Select any signal from the table.
2. **Expect**: the price panel renders individual up/down candles (open/high/low/close), not a
   single line — validates FR-001.
3. Hover over several candles.
4. **Expect**: a readout shows that candle's exact date, open, high, low, close, and volume —
   validates FR-003.
5. Drag/scroll to pan and zoom across the available history.
6. **Expect**: the visible range updates smoothly with no visible stutter, and the chart continues
   to render correctly at the new range — validates FR-002, FR-011, SC-004.
7. **Expect**: the selected signal's date is still visually marked on the chart — validates FR-004.
8. Select an instrument/signal with no price history (or simulate by picking one where the backend
   returns an empty list).
9. **Expect**: a clear "no data" state appears in place of a broken/empty canvas — validates the
   "no price history" edge case.

## 3. Validate User Story 2 — dark/light mode (P2)

1. On first load in a fresh browser profile (no prior visit), note the initial theme.
2. **Expect**: it matches the OS/browser's reported light-or-dark preference — validates FR-008.
3. Activate the theme toggle.
4. **Expect**: the entire interface (chart, filters, table, headers, status messages) switches
   immediately, with no reload — validates FR-005, FR-006.
5. Trigger the loading, empty, and error states in the new theme (e.g. stop the backend for the
   error state, filter to no results for the empty state).
6. **Expect**: each is legible and consistently styled in the active theme — validates the status
   -state edge cases.
7. Reload the page (or close/reopen the tab).
8. **Expect**: the previously chosen theme is restored automatically — validates FR-007, SC-003.

## 4. Validate User Story 3 — modernized dashboard shell (P3)

1. Filter signals by instrument, signal type, direction, and date range in various combinations.
2. Sort and page through results.
3. Select different signal rows in quick succession.
4. **Expect**: every result matches today's behavior exactly (same filtered/sorted/paginated
   results, same context panel opening) — validates FR-010, SC-005. This is also covered by the
   existing automated tests (step 6 below); this manual pass is a sanity check on the restyled
   markup.
5. Resize the browser to a typical tablet width.
6. **Expect**: no overlapping or clipped elements, no horizontal scroll — validates FR-013.

## 5. Automated checks

```sh
cd frontend
npm run lint
npm run format:check
npx tsc --noEmit    # (or: npm run build, which runs tsc then vite build)
npm test            # vitest run — existing suite must still pass unmodified in intent,
                     # plus new ThemeProvider.test.tsx and CandlestickChart.test.tsx
```

```sh
# from repository root — confirms the production Docker image still builds and serves
make docker-shell    # or: docker build --target build ./frontend && ...
```

## 6. Contract/no-regression sanity check

- Confirm `frontend/src/api/schema.d.ts` is unchanged (`git diff` shows no changes) — this feature
  must not touch the generated API client, since it makes no backend changes (see
  `contracts/ui-contracts.md`).
- Confirm no new files were added under `quantlab_specs/` other than this feature's own spec/plan
  docs — all implementation code must land under `frontend/` at the repository root (Constitution:
  Repository Structure).
