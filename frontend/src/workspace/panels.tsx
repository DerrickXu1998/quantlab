import type { FunctionComponent } from 'react';
import { CandlestickChart } from '../components/CandlestickChart';
import { SignalFilters } from '../components/SignalFilters';
import { SignalTable } from '../components/SignalTable';
import { BackendUnavailable, Loading } from '../components/StatusStates';
import { ModelCatalog } from '../workbench/ModelCatalog';
import { useWorkbench } from '../workbench/WorkbenchContext';
import { RunConfig } from '../workbench/RunConfig';
import { RunResults } from '../workbench/RunResults';
import { PAGE_SIZE, useWorkspace } from './WorkspaceContext';

/**
 * Panel ids are a compatibility surface: they are the only content identity a
 * saved layout stores. Renaming or removing one invalidates previously saved
 * layouts, which the restore fallback in useWorkspaceLayout absorbs.
 *
 * Note these components import no docking library — that seam keeps them
 * independently testable and the docking choice replaceable.
 */
export type PanelId = 'filters' | 'signals' | 'chart' | 'catalog' | 'runConfig' | 'runResults';

export interface PanelDefinition {
  id: PanelId;
  title: string;
  component: FunctionComponent;
}

function FiltersPanel() {
  const { instruments, filters, changeFilters } = useWorkspace();
  const { models } = useWorkbench();
  return (
    <div className="h-full overflow-auto p-3">
      <SignalFilters
        instruments={instruments}
        ruleNames={models.map((model) => model.name)}
        value={filters}
        onChange={changeFilters}
      />
    </div>
  );
}

function SignalsPanel() {
  const { signals, total, status, errorMessage, page, setPage, selected, setSelected } =
    useWorkspace();

  return (
    <div className="h-full overflow-auto p-3">
      {status === 'loading' && <Loading />}
      {status === 'error' && <BackendUnavailable message={errorMessage} />}
      {status === 'ready' && (
        <SignalTable
          signals={signals}
          total={total}
          selectedId={selected?.id ?? null}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
          onSelect={setSelected}
        />
      )}
    </div>
  );
}

function ChartPanel() {
  const { selected, contextBars } = useWorkspace();

  // A persistent panel with an empty state, rather than a section that appears
  // and disappears with selection — panels are stable places in a dock.
  if (!selected) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        Select a signal to see its price history.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-3" aria-label="Signal context">
      <h2 className="mb-2 shrink-0 text-sm font-semibold tracking-tight">
        {selected.symbol} — {selected.rule_name} v{selected.rule_version} on {selected.date}
      </h2>
      <div className="min-h-0 flex-1">
        {contextBars ? (
          <CandlestickChart bars={contextBars} markerDate={selected.date} />
        ) : (
          <p role="status" className="py-6 text-center text-sm text-muted-foreground">
            Loading price history…
          </p>
        )}
      </div>
    </div>
  );
}

export const PANELS: Record<PanelId, PanelDefinition> = {
  filters: { id: 'filters', title: 'Filters', component: FiltersPanel },
  signals: { id: 'signals', title: 'Signals', component: SignalsPanel },
  chart: { id: 'chart', title: 'Price', component: ChartPanel },
  catalog: { id: 'catalog', title: 'Models', component: ModelCatalog },
  runConfig: { id: 'runConfig', title: 'Run', component: RunConfig },
  runResults: { id: 'runResults', title: 'Results', component: RunResults },
};

export const PANEL_IDS = Object.keys(PANELS) as PanelId[];
