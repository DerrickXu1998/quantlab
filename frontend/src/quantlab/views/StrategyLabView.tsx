import { FlaskConical, Hourglass, ServerCrash } from 'lucide-react';
import { useEffect, useMemo } from 'react';
import { useRoute } from '../../chrome/router';
import { ModelList } from '../../components/ModelList';
import { RunConfigForm } from '../../components/RunConfigForm';
import { RunResultsView } from '../../components/RunResultsView';
import { CascadeItem } from '../chrome/Cascade';
import { EmptyState } from '../chrome/EmptyState';
import { Panel } from '../chrome/Panel';
import { useRuns } from '../../runs/RunsContext';
import type { Instrument } from '../../api/client';

/**
 * Strategies: the model registry on the left, the result of the current run
 * in the middle, the configuration form on the right.
 *
 * The run state is the app's shared store, not local state — a run created in
 * Research is already selected here, and a "Re-run this model" handoff from a
 * signal row lands as a prefilled form (`?model=…&p_<param>=…`).
 */
export function StrategyLabView({ instruments }: { instruments: Instrument[] }) {
  const {
    modelEntries,
    modelsStatus,
    selectedModel,
    selectModel,
    activeRun,
    inFlight,
    runError,
    start,
    cancel,
  } = useRuns();
  const route = useRoute();

  // The signal-row handoff: pick the named model once the registry has loaded.
  const modelParam = route.params.get('model');
  useEffect(() => {
    if (modelsStatus !== 'ready' || !modelParam) return;
    const match = modelEntries.find((entry) => entry.model.name === modelParam);
    if (match) selectModel(match.model);
    // modelEntries is derived from the same load; depending on the name keeps
    // this from re-firing on every unrelated store update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelsStatus, modelParam, modelEntries.length]);

  // Parameter prefill from the handoff: `p_<name>=<value>` pairs. Memoised on
  // the raw query string so the form does not re-seed on every render.
  const query = route.params.toString();
  const initialValues = useMemo(() => {
    const params = new URLSearchParams(query);
    const prefill: Record<string, string> = {};
    for (const [key, value] of params) {
      if (key.startsWith('p_')) prefill[key.slice(2)] = value;
    }
    return prefill;
  }, [query]);

  if (modelsStatus === 'error') {
    return (
      <EmptyState
        testId="strategies-error"
        icon={ServerCrash}
        tone="error"
        title="Backend unreachable"
        detail="The model registry could not be loaded."
      />
    );
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[240px_minmax(0,1fr)_320px]">
      <CascadeItem index={0} className="border-b border-border lg:border-b-0 lg:border-r">
        <Panel title="Models" className="border-0" bodyClassName="p-0">
          {modelsStatus === 'loading' ? (
            <EmptyState icon={Hourglass} title="Loading…" role="status" />
          ) : (
            <ModelList
              entries={modelEntries}
              selected={selectedModel?.name ?? null}
              onSelect={(name) =>
                selectModel(modelEntries.find((entry) => entry.model.name === name)?.model ?? null)
              }
            />
          )}
        </Panel>
      </CascadeItem>

      <CascadeItem index={1} className="min-w-0 p-4">
        {selectedModel ? (
          <Panel
            title={`${selectedModel.name} — backtest`}
            className="border-0"
            bodyClassName="p-0 pt-4"
            actions={
              <span className="font-mono text-[10px] text-muted-foreground">
                {selectedModel.direction_semantics}
              </span>
            }
          >
            {runError ? (
              <EmptyState
                testId="lab-run-error"
                icon={ServerCrash}
                tone="error"
                title="Backtest could not start"
                detail={runError}
              />
            ) : activeRun ? (
              <RunResultsView run={activeRun} />
            ) : (
              <EmptyState
                icon={inFlight ? Hourglass : FlaskConical}
                title={inFlight ? 'Running…' : 'Configure a backtest to see results'}
                role={inFlight ? 'status' : undefined}
              />
            )}
          </Panel>
        ) : null}
      </CascadeItem>

      <CascadeItem index={2} className="border-t border-border p-4 lg:border-l lg:border-t-0">
        {selectedModel ? (
          <Panel title="Configuration" className="border-0" bodyClassName="p-0 pt-4">
            <RunConfigForm
              model={selectedModel}
              instruments={instruments}
              running={inFlight}
              onRun={(body) => void start(body)}
              onCancel={cancel}
              initialValues={initialValues}
            />
          </Panel>
        ) : null}
      </CascadeItem>
    </div>
  );
}
