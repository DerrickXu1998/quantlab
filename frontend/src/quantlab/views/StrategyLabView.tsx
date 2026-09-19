import { ServerCrash } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  createRun,
  getRun,
  type Instrument,
  type RunDetail,
  type RunRequest,
} from '../../api/client';
import { CascadeItem } from '../chrome/Cascade';
import { EmptyState } from '../chrome/EmptyState';
import { Panel } from '../chrome/Panel';
import { useRunPerformance } from '../data/useRunPerformance';
import { useStrategies } from '../data/useStrategies';
import { BacktestConfig } from '../panels/BacktestConfig';
import { BacktestResults } from '../panels/BacktestResults';
import { StrategyList } from '../panels/StrategyList';
import { TradeLog } from '../panels/TradeLog';

export function StrategyLabView({ instruments }: { instruments: Instrument[] }) {
  const strategies = useStrategies();
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Memoised so the empty case does not hand a fresh array to the effect below
  // on every render.
  const list = useMemo(
    () => (strategies.status === 'ready' ? strategies.strategies : []),
    [strategies],
  );

  useEffect(() => {
    if (selectedName === null && list.length > 0) setSelectedName(list[0].model.name);
  }, [list, selectedName]);

  const selected = useMemo(
    () => list.find((item) => item.model.name === selectedName) ?? null,
    [list, selectedName],
  );

  const performance = useRunPerformance(
    run && run.status === 'completed' && run.signal_count > 0 ? run.id : null,
  );

  const start = async (body: RunRequest) => {
    setRunning(true);
    setRunError(null);
    setRun(null);
    try {
      const created = await createRun(body);
      setRun(await getRun(created.id));
    } catch (error: unknown) {
      setRunError(error instanceof Error ? error.message : 'the run could not be started');
    } finally {
      setRunning(false);
    }
  };

  if (strategies.status === 'error') {
    return (
      <EmptyState
        testId="strategies-error"
        icon={ServerCrash}
        tone="error"
        title="Backend unreachable"
        detail={strategies.message}
      />
    );
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[240px_minmax(0,1fr)_320px]">
      <CascadeItem index={0} className="border-b border-border lg:border-b-0 lg:border-r">
        <p className="border-b border-border px-3 py-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          Strategies
        </p>
        {strategies.status === 'loading' ? (
          <p className="px-3 py-6 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            Loading…
          </p>
        ) : (
          <StrategyList strategies={list} selected={selectedName} onSelect={setSelectedName} />
        )}
      </CascadeItem>

      <CascadeItem index={1} className="min-w-0 p-4">
        {selected ? (
          <Panel
            title={`${selected.model.name} — backtest`}
            className="border-0"
            bodyClassName="p-0 pt-4"
            actions={
              <span className="font-mono text-[10px] text-muted-foreground">
                {selected.model.direction_semantics}
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
            ) : run ? (
              <BacktestResults
                run={run}
                performance={
                  performance.status === 'ready' ? performance.performance : null
                }
                performanceError={performance.status === 'error' ? performance.message : null}
              />
            ) : (
              <p className="py-10 text-center font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                {running ? 'Running…' : 'Configure a backtest to see results'}
              </p>
            )}
          </Panel>
        ) : null}

        {run && run.status === 'completed' && performance.status === 'ready' ? (
          <div className="mt-4">
            <Panel title="Trade log" bodyClassName="p-0">
              <TradeLog trades={performance.performance.trades} />
            </Panel>
          </div>
        ) : null}
      </CascadeItem>

      <CascadeItem index={2} className="border-t border-border p-4 lg:border-l lg:border-t-0">
        {selected ? (
          <Panel title="Configuration" className="border-0" bodyClassName="p-0 pt-4">
            <BacktestConfig
              model={selected.model}
              instruments={instruments}
              running={running}
              onRun={start}
            />
          </Panel>
        ) : null}
      </CascadeItem>
    </div>
  );
}

