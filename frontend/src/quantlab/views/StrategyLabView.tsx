import { FlaskConical, ListChecks } from 'lucide-react';
import { useMemo, useState } from 'react';
import { navigate, useRoute } from '../../chrome/router';
import { StrategyBuilder, type StrategySeed } from '../../strategies/StrategyBuilder';
import type { Instrument } from '../../api/client';
import { TabBar, tabId } from '../../components/ui/tabs';
import { useInstruments } from '../../research/company/useCompany';
import { useRuns } from '../../runs/RunsContext';
import { RunsView, type RunClone } from '../../runs/RunsView';

type StrategiesTab = 'configure' | 'runs';

/**
 * Strategies: combine several signals into one set of trading rules, point it
 * at a universe of tickers, and backtest the trades.
 *
 * Two tabs. Configure builds a strategy and submits it; the backtest runs in
 * the background on the server. Runs lists every backtest with its status and
 * results. Configure stays mounted while Runs is open, so a half-built draft
 * survives a look at how the last one did.
 *
 * A signal row still hands over a rule (`?model=` with `p_<name>` values, and
 * the `symbol` it fired on): it arrives as the builder's first entry signal,
 * with that ticker as the universe. One ticker is Research; many tickers under
 * one set of rules is here.
 */
export function StrategyLabView({ instruments }: { instruments: Instrument[] }) {
  const route = useRoute();
  const { activeCount } = useRuns();
  // The whole catalogue, not the shell's eight-name watchlist it is handed:
  // a universe drawn from the first eight tickers is not a universe.
  const catalogue = useInstruments();
  const universe = catalogue.data.length > 0 ? catalogue.data : instruments;
  const query = route.params.toString();
  const tab: StrategiesTab = route.params.get('tab') === 'runs' ? 'runs' : 'configure';
  const runId = tab === 'runs' ? route.params.get('run') : null;
  const [clone, setClone] = useState<RunClone | null>(null);

  const seed = useMemo<StrategySeed | null>(() => {
    const params = new URLSearchParams(query);
    const model = params.get('model');
    if (!model) return null;
    const values: Record<string, string> = {};
    for (const [key, value] of params) {
      if (key.startsWith('p_')) values[key.slice(2)] = value;
    }
    const symbol = params.get('symbol');
    return { key: query, model, values, symbols: symbol ? [symbol] : [] };
  }, [query]);

  const show = (next: StrategiesTab, run?: string) =>
    navigate('strategies', next === 'runs' ? { tab: 'runs', ...(run ? { run } : {}) } : {});

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-4 py-2">
        <TabBar<StrategiesTab>
          label="Strategies"
          idPrefix="strategies"
          value={tab}
          onChange={(next) => show(next)}
          items={[
            { id: 'configure', label: 'Configure', icon: FlaskConical },
            {
              id: 'runs',
              label: 'Runs',
              icon: ListChecks,
              badge: activeCount,
              badgeLabel: `${activeCount} active`,
            },
          ]}
        />
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          {tab === 'configure'
            ? 'Combine several signals into one set of rules, choose a universe of tickers and submit a backtest. It runs in the background; results land in Runs. To study a single ticker, use Research.'
            : 'Every backtest, its status and its results. Open one to see its trades, or clone it back into Configure to change it.'}
        </p>
      </div>

      <div
        role="tabpanel"
        id="strategies-panel-configure"
        aria-labelledby={tabId('strategies', 'configure')}
        hidden={tab !== 'configure'}
        // `hidden` alone loses to `flex`: the class sets display and wins. The
        // builder stays mounted (a draft survives a look at Runs), so it is
        // hidden by class, not by unmounting.
        className={tab === 'configure' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}
      >
        <StrategyBuilder
          instruments={universe}
          seed={seed}
          clone={clone}
          onShowRun={(id) => show('runs', id)}
        />
      </div>
      {tab === 'runs' ? (
        <div
          role="tabpanel"
          id="strategies-panel-runs"
          aria-labelledby={tabId('strategies', 'runs')}
          className="flex min-h-0 flex-1 flex-col"
        >
          <RunsView
            runId={runId}
            onOpen={(id) => show('runs', id)}
            onBack={() => show('runs')}
            onClone={(next) => {
              setClone(next);
              show('configure');
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
