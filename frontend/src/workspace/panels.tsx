import type { FunctionComponent } from 'react';
import { ChartLine, FlaskConical, Hourglass } from 'lucide-react';
import { CandlestickChart } from '../components/CandlestickChart';
import { ModelList } from '../components/ModelList';
import { RunConfigForm } from '../components/RunConfigForm';
import { RunResultsView } from '../components/RunResultsView';
import { SignalFilters } from '../components/SignalFilters';
import { SignalTable } from '../components/SignalTable';
import { BackendUnavailable, EmptyState, Loading } from '../components/ui/empty-state';
import { useRuns } from '../runs/RunsContext';
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
  const { models } = useRuns();
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
      <EmptyState
        icon={ChartLine}
        title="No signal selected"
        detail="Select a signal to see its price history."
      />
    );
  }

  return (
    <div className="flex h-full flex-col p-3" aria-label="Signal context">
      <h2 className="mb-2 shrink-0 font-display text-sm tracking-[-0.02em]">
        {selected.symbol} — {selected.rule_name} v{selected.rule_version} on {selected.date}
      </h2>
      <div className="min-h-0 flex-1">
        {contextBars ? (
          <CandlestickChart bars={contextBars} markerDate={selected.date} />
        ) : (
          <EmptyState icon={Hourglass} title="Loading price history…" role="status" />
        )}
      </div>
    </div>
  );
}

function CatalogPanel() {
  const { modelEntries, selectedModel, selectModel } = useRuns();
  return (
    <div className="h-full overflow-auto">
      <ModelList
        entries={modelEntries}
        selected={selectedModel?.name ?? null}
        onSelect={(name) =>
          selectModel(modelEntries.find((entry) => entry.model.name === name)?.model ?? null)
        }
      />
    </div>
  );
}

function RunPanel() {
  const { instruments } = useWorkspace();
  const { selectedModel, inFlight, runError, start, cancel } = useRuns();

  if (!selectedModel) {
    return (
      <EmptyState
        icon={FlaskConical}
        title="No model selected"
        detail="Select a model to configure a run."
      />
    );
  }

  return (
    <div className="h-full overflow-auto p-3">
      <h3 className="mb-3 font-display text-sm tracking-[-0.02em]">
        {selectedModel.name}{' '}
        <span className="font-mono text-muted-foreground">v{selectedModel.version}</span>
      </h3>
      <RunConfigForm
        model={selectedModel}
        instruments={instruments}
        running={inFlight}
        onRun={(body) => void start(body)}
        onCancel={cancel}
      />
      {runError ? (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {runError}
        </p>
      ) : null}
    </div>
  );
}

function ResultsPanel() {
  const { activeRun } = useRuns();

  if (!activeRun) {
    return (
      <EmptyState
        icon={FlaskConical}
        title="No run yet"
        detail="Configure a model and run it to see results here."
      />
    );
  }

  return (
    <div className="h-full p-3">
      <RunResultsView run={activeRun} />
    </div>
  );
}

export const PANELS: Record<PanelId, PanelDefinition> = {
  filters: { id: 'filters', title: 'Filters', component: FiltersPanel },
  signals: { id: 'signals', title: 'Signals', component: SignalsPanel },
  chart: { id: 'chart', title: 'Price', component: ChartPanel },
  catalog: { id: 'catalog', title: 'Models', component: CatalogPanel },
  runConfig: { id: 'runConfig', title: 'Run', component: RunPanel },
  runResults: { id: 'runResults', title: 'Results', component: ResultsPanel },
};

export const PANEL_IDS = Object.keys(PANELS) as PanelId[];
