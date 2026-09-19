# Feature Specification: Modern Trading UI

**Feature Branch**: `003-modern-trading-ui`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "the ui looks very out of date please consider using the modern framework for a sleak look! i want the ui to support dark mode and day mode Chart engine — the K-bar itself... [full text includes chart engine and dashboard shell technology survey — see Assumptions]"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read Price Action on a Real Candlestick Chart (Priority: P1)

An analyst selects a signal to inspect and needs to see genuine open/high/low/close price action around it — not just a closing-price line — so they can judge whether the signal fired at a sensible point in the candle structure, and can pan/zoom through history to see more context.

**Why this priority**: The current chart only draws a line through closing prices, hiding the exact information (intraday range, direction of the bar) that a K-bar chart exists to show. This is the single most visible symptom of the "out of date" complaint and the primary tool analysts use to judge a signal.

**Independent Test**: Can be fully tested by selecting any signal with available price history and confirming the chart renders each period as an open/high/low/close candle (not a line), supports pan and zoom, shows a hover readout with exact OHLCV values, and still marks the selected signal's date — delivering a trustworthy, exploratory view of price action on its own.

**Acceptance Scenarios**:

1. **Given** a signal with available price history is selected, **When** the price panel loads, **Then** each trading period is rendered as a distinct up/down candle showing open, high, low, and close (not a single line).
2. **Given** a rendered candlestick chart, **When** the user hovers over any candle, **Then** a readout appears showing that period's exact date, open, high, low, close, and volume.
3. **Given** a rendered candlestick chart with more history than fits on screen, **When** the user drags/scrolls to pan or zoom, **Then** the visible range updates smoothly and the chart continues to render correctly at the new range.
4. **Given** a selected signal, **When** the chart renders, **Then** the signal's date is still visually marked on the chart, equivalent to the current marker behavior.
5. **Given** an instrument with a long price history, **When** the chart is displayed, **Then** panning and zooming remain smooth with no visible stutter or lag.

---

### User Story 2 - Switch Between Dark Mode and Light Mode (Priority: P2)

A user working at night wants a dark interface to reduce eye strain, while a user working in a bright office wants the current light look; both want the choice to be a single, obvious action that applies everywhere and is remembered next time.

**Why this priority**: Explicitly requested by name ("dark mode and day mode") and affects every page and component, making it a highly visible, whole-app change independent of the chart work.

**Independent Test**: Can be fully tested by toggling the theme control and confirming every visible surface (chart, filters, table, status messages) switches palette immediately, and that reloading the app later restores the same choice — delivering a complete, usable theme switch on its own even before any other visual restyling ships.

**Acceptance Scenarios**:

1. **Given** the app is open in light mode, **When** the user activates the theme control, **Then** the entire interface (chart, filters panel, signal table, headers, status messages) switches to dark mode immediately, with no page reload required.
2. **Given** the user has switched to dark mode, **When** they close and later reopen the app on the same device/browser, **Then** the app opens in dark mode without the user having to re-select it.
3. **Given** a user who has never set a preference in this app, **When** they open the app for the first time, **Then** the app's initial theme matches their operating system's/browser's reported light-or-dark preference.
4. **Given** the app is in dark mode, **When** any error, loading, or empty state is shown, **Then** it is legible and styled consistently with the dark theme (not a leftover light-themed panel).

---

### User Story 3 - Browse a Modernized, Consistent Dashboard (Priority: P3)

An analyst using the filters, signal table, and pagination controls wants the surrounding dashboard to look and feel like a current, professional analytics product rather than an unstyled form, while every existing filter, sort, and selection behavior continues to work exactly as before.

**Why this priority**: This is the general "sleek look" polish that ties the chart and theme work together into one coherent product; it's lower priority than the chart and theme changes because it delivers no new capability on its own — it re-styles what already works.

**Independent Test**: Can be fully tested by performing every existing workflow (filter by instrument/type/direction/date, sort, page through results, select a signal) against the restyled interface and confirming each behaves identically to today while presenting with modern layout, typography, and spacing — delivering a coherent visual refresh that is verifiable without touching the chart or theme logic.

**Acceptance Scenarios**:

1. **Given** the restyled dashboard, **When** a user filters signals by instrument, signal type, direction, or date range, **Then** the results update exactly as they do today.
2. **Given** the restyled signal table, **When** a user sorts or pages through results, **Then** sorting and pagination behave exactly as they do today.
3. **Given** the restyled dashboard, **When** a user selects a signal row, **Then** the price chart context panel opens exactly as it does today.
4. **Given** the restyled dashboard on a typical desktop or tablet screen width, **When** the page is viewed, **Then** all controls and the chart remain fully visible and usable without horizontal scrolling or overlapping elements.

---

### Edge Cases

- What happens when the selected signal's instrument has no price history available? The chart area MUST show a clear "no data" state styled consistently in both themes, not a broken/empty chart canvas.
- What happens when price history has only one bar, or gaps from non-trading days? The chart MUST render without errors and the signal marker MUST still appear on the correct date.
- What happens when the backend is unreachable? The existing "backend unavailable" state MUST still appear, restyled to match the new look in both themes.
- What happens when a user selects one signal, then quickly selects another before the first chart finishes loading? The chart MUST show the most recently selected signal's data, discarding any stale in-flight response.
- What happens when the operating system's theme changes while the app is open (e.g., automatic day/night switching)? The app is not required to react live to an OS-level change mid-session, but MUST pick up the new OS preference the next time it loads with no saved in-app preference.
- What happens when no signals match the current filters? The empty state MUST be restyled consistently and remain distinguishable from the loading and error states in both themes.
- What happens for keyboard-only or screen-reader users? The theme toggle, filters, and table MUST remain operable via keyboard, and color contrast MUST remain adequate in both themes.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST render an instrument's price history as a candlestick (open/high/low/close) chart instead of a single closing-price line.
- **FR-002**: Chart MUST support interactive panning and zooming across the full available price history.
- **FR-003**: Chart MUST display, on hover, the exact date, open, high, low, close, and volume for the period under the cursor.
- **FR-004**: Chart MUST continue to visually mark the date of the currently selected signal, equivalent to today's marker.
- **FR-005**: System MUST provide a single, always-accessible control that lets users switch between dark mode and light mode.
- **FR-006**: System MUST apply the active theme consistently across every page and component, including loading, error, and empty states.
- **FR-007**: System MUST remember the user's chosen theme on their device/browser and restore it on the next visit.
- **FR-008**: When no theme preference has been saved yet, system MUST default to the operating system's/browser's reported light-or-dark preference.
- **FR-009**: System MUST restyle the filters panel, signal table, headers, and status messages (loading/error/empty) to a modern, consistent visual design in both themes.
- **FR-010**: System MUST preserve all existing behaviors unchanged: filtering by instrument, signal type, direction, and date range; sorting; pagination; and selecting a signal to view its price context.
- **FR-011**: Chart panning and zooming MUST remain smooth, with no visible stutter, across at least several years of daily price history for a single instrument.
- **FR-012**: All interactive controls (theme toggle, filters, table rows/sorting, pagination) MUST remain operable via keyboard and MUST meet standard color-contrast expectations in both themes.
- **FR-013**: Layout MUST remain fully usable, with no overlapping or clipped elements, at common desktop and tablet screen widths.

### Key Entities

- **Theme Preference**: The user's chosen display mode (light or dark), stored per device/browser; not tied to a user account since the application has no authentication today.
- **Price Bar** *(existing)*: A single period's open, high, low, close, and volume for an instrument — already available from the backend and now fully visualized rather than reduced to its closing price.
- **Signal** *(existing)*: An unchanged domain entity; this feature only changes how signals and their price context are presented, not their data or computation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any selected signal with price history, a user can see the open, high, low, and close of every rendered period at a glance, without any extra clicks.
- **SC-002**: A user can switch the entire interface between light and dark mode in a single action, with all visible surfaces updated instantly.
- **SC-003**: Returning users see their previously chosen theme applied automatically on 100% of subsequent visits, with no re-selection needed.
- **SC-004**: The price chart remains smooth to pan and zoom (no perceptible lag) across at least two years of daily price history for a single instrument.
- **SC-005**: Every filter, sort, pagination, and signal-selection workflow that works today continues to produce identical results after the redesign, with zero behavioral regressions.
- **SC-006**: In an informal side-by-side comparison, reviewers consistently describe the redesigned interface as modern/professional compared to the prior version.

## Assumptions

- **Scope is a visual/interaction modernization of the existing Signal Viewer, not a new product surface.** The user's message included broad background on trading-dashboard architecture (chart engine options, dashboard-shell component kits, and even a hypothetical full-stack rewrite). This spec treats that as context for the implementation approach, not as a request to introduce new domains such as positions, orders, or KPI cards that the backend does not currently support ([[Constitution]] Principle I: Library-First — new domains need their own library and data model, which is out of scope here). If broader dashboard panels are in fact wanted, that should be scoped as a follow-up feature once the underlying data exists.
- **Backend and API contracts are unchanged.** All data needed for candlestick rendering (open, high, low, close, volume) is already returned by the existing price endpoint; this feature is frontend-only, consistent with Constitution Principle V (frontend does not perform analytical computation, and the typed API boundary stays authoritative).
- **No new technical indicator overlays (moving averages, RSI, MACD, etc.) are added as part of this feature.** The ask is to modernize how existing price and signal data is displayed, not to add new analytical computations; indicator overlays would be a separate, backend-touching feature.
- **Theme preference is stored locally per device/browser**, since the application has no user accounts or authentication today. If accounts are added later, syncing theme preference across devices could be revisited.
- **"Modern framework for a sleek look" and the specific chart/UI libraries mentioned by the user are implementation choices for the planning phase**, not requirements of this spec, which stays focused on user-observable outcomes (candlestick rendering, pan/zoom, theming, consistent restyling, no regressions).
- **Desktop and tablet screen widths are the supported range**; phone-width layouts are not required, consistent with this being an internal analyst-facing research tool rather than a consumer product.
- **"Several years of daily history" is the performance bar**, reflecting the actual scale of daily OHLCV data this application handles today, rather than the much larger intraday/tick volumes some chart engines are built for.
