import type { DockviewApi } from 'dockview-react';
import { PANELS } from './panels';

/**
 * The one default-layout builder.
 *
 * Both reset-to-default (FR-007) and the restore-failure fallback (FR-008) call
 * this, so those two paths cannot drift apart.
 */
export function buildDefaultLayout(api: DockviewApi): void {
  api.addPanel({
    id: PANELS.filters.id,
    component: PANELS.filters.id,
    title: PANELS.filters.title,
  });

  api.addPanel({
    id: PANELS.signals.id,
    component: PANELS.signals.id,
    title: PANELS.signals.title,
    position: { referencePanel: PANELS.filters.id, direction: 'below' },
  });

  api.addPanel({
    id: PANELS.chart.id,
    component: PANELS.chart.id,
    title: PANELS.chart.title,
    position: { referencePanel: PANELS.signals.id, direction: 'right' },
  });

  // Workbench panels: the catalog beside the filters, and the run
  // configuration / results stacked with the chart so an experiment and its
  // price context share the same region.
  api.addPanel({
    id: PANELS.catalog.id,
    component: PANELS.catalog.id,
    title: PANELS.catalog.title,
    position: { referencePanel: PANELS.filters.id, direction: 'right' },
  });

  api.addPanel({
    id: PANELS.runConfig.id,
    component: PANELS.runConfig.id,
    title: PANELS.runConfig.title,
    position: { referencePanel: PANELS.signals.id, direction: 'below' },
  });

  api.addPanel({
    id: PANELS.runResults.id,
    component: PANELS.runResults.id,
    title: PANELS.runResults.title,
    position: { referencePanel: PANELS.chart.id, direction: 'within' },
  });
}
