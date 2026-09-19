import { FlaskConical, ServerCrash } from 'lucide-react';
import type { Instrument } from '../../api/client';
import { EquityCurve } from '../charts/EquityCurve';
import { CascadeItem } from '../chrome/Cascade';
import { EmptyState } from '../chrome/EmptyState';
import { Chip, FloatingChips } from '../chrome/FloatingChips';
import { Numeric } from '../chrome/Numeric';
import { Panel } from '../chrome/Panel';
import { useLatestRun } from '../data/useLatestRun';
import { useRunPerformance } from '../data/useRunPerformance';
import { Assumptions } from '../panels/Assumptions';
import { PortfolioSummary } from '../panels/PortfolioSummary';
import { PositionsTable } from '../panels/PositionsTable';
import { StatRow } from '../panels/StatRow';
import { WatchlistRail } from '../panels/WatchlistRail';

const SIM_FEED = 'QuantLab serves end-of-day bars and has no streaming feed; the movement is simulated.';

export function OverviewView({
  instruments,
  feedError,
  selected,
  onSelect,
  onOpenStrategyLab,
}: {
  instruments: Instrument[];
  feedError: string | null;
  selected: string | null;
  onSelect: (symbol: string) => void;
  onOpenStrategyLab: () => void;
}) {
  const latest = useLatestRun();
  const runId = latest.status === 'ready' ? latest.run.id : null;
  const performance = useRunPerformance(runId);

  if (latest.status === 'error') {
    return (
      <EmptyState
        testId="overview-error"
        icon={ServerCrash}
        tone="error"
        title="Backend unreachable"
        detail={latest.message}
      />
    );
  }

  return (
    // Asymmetric on purpose: a fixed 240px rail against a fluid workspace,
    // rather than an even split that would read as a dashboard.
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)]">
      <CascadeItem index={0} className="hidden border-r border-border lg:block">
        <p className="border-b border-border px-3 py-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          Watchlist
        </p>
        <WatchlistRail
          instruments={instruments}
          selected={selected}
          onSelect={onSelect}
          error={feedError}
        />
      </CascadeItem>

      <div className="min-w-0 overflow-y-auto">
        {latest.status === 'empty' ? (
          <EmptyState
            testId="overview-no-runs"
            icon={FlaskConical}
            title="No runs yet"
            detail="Overview reports on the most recent completed experiment. Run a strategy to populate it."
            action={
              <button
                type="button"
                onClick={onOpenStrategyLab}
                className="mt-2 rounded-sm border border-primary/50 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-primary hover:bg-primary/10"
              >
                Open Strategy Lab
              </button>
            }
          />
        ) : latest.status === 'ready' && performance.status === 'ready' ? (
          <>
            <CascadeItem index={1}>
              <PortfolioSummary run={latest.run} performance={performance.performance} />
            </CascadeItem>

            <div className="grid grid-cols-1 gap-px bg-border xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
              <CascadeItem index={2} className="relative bg-background">
                {/* Deliberately crossing the panel's top edge. */}
                <FloatingChips>
                  <Chip label="Bars" title="Sessions marked in the reported window">
                    <Numeric
                      value={performance.performance.equity.length}
                      format="integer"
                      className="text-[11px]"
                    />
                  </Chip>
                  <Chip label="Trades">
                    <Numeric
                      value={performance.performance.metrics.trade_count}
                      format="integer"
                      className="text-[11px]"
                    />
                  </Chip>
                  <Chip label="Book">
                    <Numeric
                      value={performance.performance.initial_capital}
                      format="currency"
                      tone="muted"
                      className="text-[11px]"
                    />
                  </Chip>
                </FloatingChips>
                <Panel title="Equity curve" className="border-0">
                  <StatRow metrics={performance.performance.metrics} />
                  <div className="mt-6">
                    <EquityCurve
                      equity={performance.performance.equity}
                      benchmark={performance.performance.benchmark}
                      benchmarkLabel="Buy & hold"
                    />
                  </div>
                  <Assumptions assumptions={performance.performance.assumptions} />
                </Panel>
              </CascadeItem>

              <CascadeItem index={3} className="bg-background">
                <Panel
                  title="Open positions"
                  className="border-0"
                  bodyClassName="p-0"
                  simulated="The live column re-marks against the simulated feed."
                >
                  <PositionsTable trades={performance.performance.trades} />
                </Panel>
              </CascadeItem>
            </div>
          </>
        ) : performance.status === 'error' ? (
          <EmptyState
            testId="overview-performance-error"
            icon={ServerCrash}
            tone="error"
            title="Could not load performance"
            detail={performance.message}
          />
        ) : (
          <p className="px-8 py-10 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            Loading…
          </p>
        )}
      </div>
    </div>
  );
}

export { SIM_FEED };
