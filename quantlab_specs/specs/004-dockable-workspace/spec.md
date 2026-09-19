# Feature Specification: Dockable Workspace

**Feature Branch**: `004-dockable-workspace`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "i think i want to use Dockview — zero-dependency docking manager: tabs, drag-to-split, floating panels, serializable layouts. Closest thing to the real article. to realign my front end if that is good"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Arrange the Workspace to Fit the Task (Priority: P1)

An analyst reviewing signals wants to arrange the workspace the way a trading terminal works: drag the
chart to sit beside the signal list instead of below it, widen the chart when reading price action,
shrink the filters out of the way, or stack panels as tabs when screen space is tight — rather than
accepting one fixed vertical stack.

**Why this priority**: This is the entire point of the change. Today's layout is a fixed top-to-bottom
stack (filters → table → chart), which forces scrolling to compare a signal row against its price
action. Rearranging is the capability that makes the workspace feel like a real terminal, and it
delivers value on its own even before layouts persist.

**Independent Test**: Can be fully tested by dragging each panel to a new position (split left/right,
split top/bottom, stack as a tab), resizing the dividers, and confirming each panel continues to work
normally in its new position — delivering a usable, rearrangeable workspace without any persistence.

**Acceptance Scenarios**:

1. **Given** the default workspace, **When** the user drags the chart panel to the right edge of the
   signal list, **Then** the two panels sit side by side and both remain fully interactive.
2. **Given** two panels side by side, **When** the user drags the divider between them, **Then** both
   panels resize smoothly and their contents reflow to the new dimensions.
3. **Given** two panels, **When** the user drags one panel onto another's tab strip, **Then** they
   become a tabbed group and the user can switch between them by clicking tabs.
4. **Given** the chart panel has been resized or moved, **When** the user looks at the chart, **Then**
   the chart has redrawn to fill its new panel size — never clipped, stretched, or collapsed to zero
   height.
5. **Given** a signal is selected, **When** the user rearranges panels, **Then** the selection and all
   loaded data are preserved — rearranging never re-fetches or resets the user's place.

---

### User Story 2 - Keep My Layout, and Get Back to Default (Priority: P2)

A user who has arranged the workspace to their liking wants it still there tomorrow, and — just as
importantly — wants a reliable way back to the default arrangement if they drag themselves into a
layout they don't want.

**Why this priority**: A rearrangeable workspace that forgets its arrangement on every reload is
actively annoying, and one that can be broken with no way back is worse. This pairs persistence with
its safety net, and is independently valuable once rearranging (P1) works.

**Independent Test**: Can be fully tested by rearranging panels, reloading the app, confirming the
arrangement is restored, then using the reset control and confirming the default arrangement returns —
verifiable without floating panels existing.

**Acceptance Scenarios**:

1. **Given** the user has rearranged the workspace, **When** they reload the app, **Then** the
   workspace is restored to their arrangement, not the default.
2. **Given** a restored layout, **When** the app loads, **Then** panel sizes, positions, tab grouping,
   and which tab was active are all preserved.
3. **Given** any arrangement, **When** the user activates the reset control, **Then** the workspace
   returns to the default arrangement immediately.
4. **Given** a user who has closed one or more panels, **When** they want a closed panel back,
   **Then** they can reopen it without resetting the whole workspace.
5. **Given** a saved layout that can no longer be applied (corrupt, or referring to panels that no
   longer exist), **When** the app loads, **Then** it falls back to the default arrangement and the
   user sees a working workspace rather than an error or blank screen.

---

### User Story 3 - Float a Panel Out of the Grid (Priority: P3)

An analyst studying price action wants to pull the chart out into a floating window that sits above
the workspace, size it freely, and move it aside — without giving up the rest of the layout
underneath.

**Why this priority**: Floating adds real value for focused study on large or multi-monitor setups,
but it's the least essential of the three: the docked grid (P1) plus persistence (P2) already deliver
a terminal-like workspace. Lowest risk to defer.

**Independent Test**: Can be fully tested by floating a panel, moving and resizing it, and docking it
back into the grid, confirming the panel works identically in all three states.

**Acceptance Scenarios**:

1. **Given** a docked panel, **When** the user floats it, **Then** it becomes a freely movable,
   resizable window above the workspace and remains fully interactive.
2. **Given** a floating panel, **When** the user drags it back into the grid, **Then** it docks into
   the drop position and the floating window disappears.
3. **Given** a floating chart panel, **When** it is resized, **Then** the chart redraws to fill the
   new size correctly.
4. **Given** floating panels are open, **When** the layout is saved and restored, **Then** floating
   panels return as floating, with their position and size.

---

### Edge Cases

- **A chart in a hidden or inactive tab**: when a chart panel is mounted in a background tab and then
  brought to the front, it MUST render at the correct size rather than collapsing to zero height or
  keeping a stale size. (Charts measure their container to draw; a container with no size while hidden
  is the single most common way docking breaks charts.)
- **Rapid or extreme resizing**: dragging a divider quickly, or collapsing a panel to its minimum,
  MUST NOT leave the chart blank, mis-scaled, or throw errors.
- **A saved layout from an older app version** that references a panel type no longer present MUST
  load the panels it still recognises and drop the rest, rather than failing wholesale.
- **All panels closed**: the user MUST always have a visible route back to a working workspace.
- **Narrow screens**: below a usable docking width, the workspace MUST remain readable and usable
  rather than presenting unusably small drag targets.
- **Theme switching**: dock chrome — tab strips, borders, drag indicators, floating window frames —
  MUST follow the active light/dark theme, with no leftover light-themed chrome in dark mode.
- **Keyboard and screen-reader users**: dragging is a pointer-only gesture; panel navigation and any
  layout action essential to using the app MUST NOT be reachable exclusively by drag.
- **Empty panel states**: a panel with nothing to show (e.g. no signal selected) MUST show a clear
  empty state rather than blank space.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The workspace MUST present the existing Signal Viewer regions — filters, signal list, and
  price chart — as independently arrangeable panels.
- **FR-002**: Users MUST be able to rearrange panels by dragging them to split a region horizontally or
  vertically.
- **FR-003**: Users MUST be able to resize panels by dragging the dividers between them.
- **FR-004**: Users MUST be able to group panels into a tabbed set and switch between them by tab.
- **FR-005**: Users MUST be able to close a panel and later reopen it without resetting the whole
  workspace.
- **FR-006**: The system MUST persist the user's layout — positions, sizes, tab grouping, and active
  tab — and restore it on their next visit on the same device/browser.
- **FR-007**: The system MUST provide a control that restores the default layout at any time.
- **FR-008**: When a saved layout cannot be applied, the system MUST fall back to the default layout
  and continue working, without surfacing an error state or a blank workspace.
- **FR-009**: Panel contents MUST re-render correctly at their new size whenever a panel is resized,
  moved, floated, or revealed from an inactive tab — with no clipped, stale, or zero-height rendering.
- **FR-010**: All existing behavior MUST be preserved: filtering, sorting, pagination, selecting a
  signal, and viewing its price context work exactly as they do today.
- **FR-011**: Selection and loaded data MUST survive layout changes — rearranging panels MUST NOT
  reset the user's selection or trigger redundant refetching.
- **FR-012**: Dock chrome (tab strips, borders, drag indicators, floating frames) MUST follow the
  active light/dark theme.
- **FR-013**: Users MUST be able to float a panel into a movable, resizable window above the workspace,
  and dock it back into the grid.
- **FR-014**: Panels MUST remain reachable and operable without pointer dragging, so the app stays
  usable for keyboard and assistive-technology users.

### Key Entities

- **Workspace Layout**: The saved arrangement of the workspace — which panels exist, their positions
  and sizes, how they are grouped into tabs, which tab is active, and which panels are floating (with
  position and size). Stored per device/browser, since the application has no user accounts.
- **Panel**: One arrangeable region of the workspace, identified by a stable type (filters, signal
  list, price chart) plus a title shown on its tab. Panel identity is what lets a saved layout be
  matched back to real content on reload.
- **Signal** and **Price Bar** *(existing)*: Unchanged. This feature changes only how the surfaces that
  display them are arranged, not the data or how it is fetched.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can place the signal list and the price chart side by side in under 10 seconds,
  using only drag, without instructions.
- **SC-002**: A returning user finds their arranged workspace restored on 100% of subsequent visits to
  the same browser, with no manual rearranging.
- **SC-003**: A user who has rearranged the workspace into a state they dislike can return to the
  default in a single action.
- **SC-004**: The chart renders at the correct size in 100% of resize, move, float, and tab-reveal
  cases — zero occurrences of blank, clipped, or zero-height charts.
- **SC-005**: Every filter, sort, pagination, and signal-selection workflow that works today produces
  identical results after the change, with zero behavioral regressions.
- **SC-006**: A corrupt or outdated saved layout never prevents the user from reaching a working
  workspace.
- **SC-007**: Rearranging panels causes no additional data requests beyond what the same actions
  trigger today.

## Assumptions

- **This is a layout-shell change, not a new analytics surface.** The panels being made arrangeable are
  the three that exist today (filters, signal list, price chart). Adding *new* panel types — positions,
  orders, KPI tiles, additional analytics — is out of scope here and would need its own feature once
  the backing data exists, consistent with the constitution's Library-First principle.
- **Multiple simultaneous chart panels (e.g. comparing two instruments side by side) are out of
  scope.** Docking makes this newly possible and it is the natural follow-up, but it requires new
  selection semantics (today exactly one signal is selected at a time) and is a functional change
  rather than a layout change.
- **Adopting a docking workspace is a bet on a multi-panel future.** For three panels alone, a docking
  manager is more machinery than the layout strictly needs; it earns its place if the product is headed
  toward a terminal with many panels. This assumption should be revisited if that direction changes,
  since the simpler alternative is a fixed two-column responsive layout.
- **The price chart becomes a persistent panel** showing an empty state when no signal is selected,
  rather than appearing and disappearing with selection. A panel that vanishes on deselect would fight
  the docking model, where panels are stable places rather than transient sections.
- **Layout is stored locally per device/browser**, since the application has no accounts — the same
  approach already used for the theme preference. Syncing layouts across devices could be revisited if
  accounts are ever added.
- **Docking targets desktop-sized screens.** Drag-to-split is a pointer-driven, space-hungry
  interaction; below a usable width the workspace is expected to fall back to a simple stacked
  arrangement rather than offering unusable drag targets.
- **Backend, API contracts, and data flow are unchanged** — this is a frontend layout change only, and
  the existing typed API boundary stays authoritative.
- **The specific docking library is an implementation choice for the planning phase.** The stakeholder
  has proposed Dockview (verified: zero runtime dependencies beyond its own core package), and this
  spec is written so any implementation delivering these behaviors satisfies it.
