import type { DockviewApi } from 'dockview-react';
import { PANELS } from './panels';

/**
 * The floor a dock cell may be dragged to.
 *
 * A panel can be resized to nothing, and a panel resized to nothing reads as a
 * rendering fault rather than a choice. Every panel keeps enough room for its
 * header and a line or two of content; below that the sash simply stops.
 */
const MIN = { minimumHeight: 120, minimumWidth: 240 } as const;

/**
 * What the filter row is worth on first run.
 *
 * The filter form is a fixed set of controls and wants roughly its own height;
 * the signal table wants everything else. Left to dockview's even split the
 * left column came out 338 / 152 / 152 on a 900px screen — a void under the
 * filters and two visible signal rows under a table that is the whole point of
 * the destination.
 */
const FILTERS_HEIGHT = 248;

/**
 * The one default-layout builder.
 *
 * Both reset-to-default (FR-007) and the restore-failure fallback (FR-008) call
 * this, so those two paths cannot drift apart.
 *
 * Four regions, not five: three stacked rows do not fit in a 900px column
 * without one of them being unusable, so the run form shares the workbench
 * region with the price chart and the results it produces. It is added last and
 * is therefore the active tab — the thing you do next when nothing has run yet.
 */
export function buildDefaultLayout(api: DockviewApi): void {
  api.addPanel({
    id: PANELS.filters.id,
    component: PANELS.filters.id,
    title: PANELS.filters.title,
    ...MIN,
  });

  api.addPanel({
    id: PANELS.signals.id,
    component: PANELS.signals.id,
    title: PANELS.signals.title,
    position: { referencePanel: PANELS.filters.id, direction: 'below' },
    ...MIN,
  });

  api.addPanel({
    id: PANELS.chart.id,
    component: PANELS.chart.id,
    title: PANELS.chart.title,
    position: { referencePanel: PANELS.signals.id, direction: 'right' },
    ...MIN,
  });

  // Workbench panels: the catalog beside the filters, and the run form and its
  // results stacked with the chart so an experiment and its price context share
  // the same region.
  api.addPanel({
    id: PANELS.catalog.id,
    component: PANELS.catalog.id,
    title: PANELS.catalog.title,
    position: { referencePanel: PANELS.filters.id, direction: 'right' },
    ...MIN,
  });

  api.addPanel({
    id: PANELS.runResults.id,
    component: PANELS.runResults.id,
    title: PANELS.runResults.title,
    position: { referencePanel: PANELS.chart.id, direction: 'within' },
    ...MIN,
  });

  api.addPanel({
    id: PANELS.runConfig.id,
    component: PANELS.runConfig.id,
    title: PANELS.runConfig.title,
    position: { referencePanel: PANELS.chart.id, direction: 'within' },
    ...MIN,
  });

  // Sizing the neighbour is what shrinks the filter row: dockview sizes the
  // panel being added, not the one it was added against, so the share is set
  // once the column exists.
  api.getPanel(PANELS.filters.id)?.api.setSize({ height: FILTERS_HEIGHT });
}
