import { FlaskConical, Hourglass, ServerCrash } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useRoute } from '../../chrome/router';
import { ModelList } from '../../components/ModelList';
import { RunConfigForm } from '../../components/RunConfigForm';
import { RunResultsView } from '../../components/RunResultsView';
import { FundamentalsInspector } from '../../strategies/FundamentalsInspector';
import { StrategyBuilder } from '../../strategies/StrategyBuilder';
import { useDataWindow } from '../../workbench/useDataWindow';
import { CascadeItem } from '../chrome/Cascade';
import { EmptyState } from '../chrome/EmptyState';
import { Panel } from '../chrome/Panel';
import { useRuns } from '../../runs/RunsContext';
import type { Instrument } from '../../api/client';

type Mode = 'builder' | 'signal' | 'inspector';

/**
 * Strategies: the destination where a strategy is assembled, and where a
 * single rule can still be taken for a quick run on its own.
 *
 * Two modes rather than two destinations. They share the runs store, so a
 * result found by running one signal is still on screen after switching to the
 * builder to wrap it in filters and execution criteria — which is the actual
 * path people take, and splitting it across the nav would have made it a
 * round trip.
 *
 * The builder is the default. A `?model=` handoff from a signal row means
 * "configure this one rule", so that arrives in the signal lab instead.
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
  const modelParam = route.params.get('model');
  const modeParam = route.params.get('mode');
  const symbolParam = route.params.get('symbol');
  const asOfParam = route.params.get('as_of');
  const [mode, setMode] = useState<Mode>(() =>
    modeParam === 'inspector' ? 'inspector' : modelParam ? 'signal' : 'builder',
  );

  // The inspector's subject. Seeded from the hash so the builder's coverage
  // warning can hand a name over ("this one can never trade — here is what it
  // knew"), and editable from inside the inspector afterwards.
  const { endDate } = useDataWindow(instruments);
  const [subject, setSubject] = useState<string | null>(symbolParam);
  const [asOf, setAsOf] = useState<string>(asOfParam ?? '');
  const inspectorDate = asOf || asOfParam || endDate;

  // A handoff from another screen switches the mode and the subject together;
  // a change made inside the inspector does not write back to the hash, so
  // the back button still leaves the destination rather than stepping through
  // every date the researcher tried.
  useEffect(() => {
    if (modeParam !== 'inspector') return;
    setMode('inspector');
    if (symbolParam) setSubject(symbolParam);
    if (asOfParam) setAsOf(asOfParam);
  }, [modeParam, symbolParam, asOfParam]);

  // The signal-row handoff: pick the named model once the registry has loaded,
  // and show the surface that can configure it.
  useEffect(() => {
    if (!modelParam) return;
    setMode('signal');
    if (modelsStatus !== 'ready') return;
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

  const tab = (value: Mode, label: string, hint: string) => (
    <button
      key={value}
      type="button"
      role="tab"
      aria-selected={mode === value}
      title={hint}
      onClick={() => setMode(value)}
      className={`border-b-2 px-3 py-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary ${
        mode === value
          ? 'border-b-primary text-primary'
          : 'border-b-transparent text-muted-foreground hover:text-foreground'
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        role="tablist"
        aria-label="Strategies mode"
        className="flex shrink-0 items-center gap-1 border-b border-border px-4"
      >
        {tab('builder', 'Strategy builder', 'Combine several signals into one strategy.')}
        {tab('signal', 'Signal lab', 'Run a single registered rule on its own.')}
        {tab(
          'inspector',
          'Point-in-time',
          'What had actually been filed for an instrument on a given date.',
        )}
      </div>

      {mode === 'builder' ? (
        <StrategyBuilder instruments={instruments} />
      ) : mode === 'inspector' ? (
        <FundamentalsInspector
          instruments={instruments}
          symbol={subject}
          asOf={inspectorDate}
          onSymbolChange={setSubject}
          onAsOfChange={setAsOf}
        />
      ) : modelsStatus === 'error' ? (
        <EmptyState
          testId="strategies-error"
          icon={ServerCrash}
          tone="error"
          title="Backend unreachable"
          detail="The model registry could not be loaded."
        />
      ) : (
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
                    selectModel(
                      modelEntries.find((entry) => entry.model.name === name)?.model ?? null,
                    )
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
                    detail={
                      inFlight
                        ? undefined
                        : 'Choose instruments and a window on the right, then run. Results appear here.'
                    }
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
      )}
    </div>
  );
}
