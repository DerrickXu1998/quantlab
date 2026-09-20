import { FlaskConical, Hourglass, ServerCrash } from 'lucide-react';
import { useEffect } from 'react';
import { useDataset } from '../../api/DatasetProvider';
import { navigate, useRoute } from '../../chrome/router';
import { Button } from '../../components/ui/button';
import { EmptyState } from '../../components/ui/empty-state';
import { Numeric } from '../../components/ui/numeric';
import { RunsRail } from '../../components/RunsRail';
import { DatasetBadge } from '../../workbench/DatasetBadge';
import { useRuns } from '../../runs/RunsContext';
import { EquityCurve } from '../charts/EquityCurve';
import { FillColumn } from '../../components/ui/layout';
import { CascadeItem } from '../chrome/Cascade';
import { Chip, FloatingChips } from '../chrome/FloatingChips';
import { Panel } from '../chrome/Panel';
import { useRunPerformance } from '../data/useRunPerformance';
import { Assumptions } from '../panels/Assumptions';
import { PortfolioSummary } from '../panels/PortfolioSummary';
import { PositionsTable } from '../panels/PositionsTable';
import { StatRow } from '../panels/StatRow';

/**
 * The first-run experience, when no run exists at all: three steps, each one
 * click from a result.
 */
function FirstRun() {
  const dataset = useDataset();
  const signalCount = dataset.status === 'ready' ? dataset.health.signal_count : null;

  return (
    <div data-testid="overview-no-runs" className="p-4">
      <Panel title="No runs yet" className="border-0">
        <ol className="space-y-4">
          <li className="flex items-start gap-3">
            <span className="font-mono text-[11px] text-muted-foreground">01</span>
            <div>
              <p className="flex items-center gap-2 text-xs">
                Know your data <DatasetBadge />
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Everything the app shows traces back to this source.
              </p>
            </div>
          </li>
          <li className="flex items-start gap-3">
            <span className="font-mono text-[11px] text-muted-foreground">02</span>
            <div>
              <Button type="button" size="sm" onClick={() => navigate('strategies')}>
                Run your first backtest
              </Button>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Strategies opens with the first registered model preselected.
              </p>
            </div>
          </li>
          <li className="flex items-start gap-3">
            <span className="font-mono text-[11px] text-muted-foreground">03</span>
            <div>
              <Button type="button" size="sm" variant="outline" onClick={() => navigate('research')}>
                Explore stored signals
              </Button>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {signalCount !== null ? (
                  <>
                    <Numeric value={signalCount} format="integer" /> stored signals from the seeded
                    dataset.
                  </>
                ) : (
                  'Signals stored in the dataset, before you run anything yourself.'
                )}
              </p>
            </div>
          </li>
        </ol>
      </Panel>
    </div>
  );
}

/**
 * Overview is run-centric: the saved-runs rail is the primary content, and
 * selecting a run loads its detail and performance into the hero, the equity
 * curve and the open positions. With nothing saved it degrades to the latest
 * completed run; with no runs at all it is the first-run guide.
 */
export function OverviewView() {
  const { allRuns, runsStatus, latestCompleted, activeRun, select } = useRuns();
  const route = useRoute();
  const paramId = route.params.get('run');
  const targetId = paramId ?? latestCompleted?.id ?? null;

  useEffect(() => {
    if (targetId && activeRun?.id !== targetId) void select(targetId);
  }, [targetId, activeRun?.id, select]);

  const run = activeRun && activeRun.id === targetId ? activeRun : null;
  const performance = useRunPerformance(run && run.status === 'completed' ? run.id : null);

  if (runsStatus === 'error') {
    return (
      <EmptyState
        testId="overview-error"
        icon={ServerCrash}
        tone="error"
        title="Backend unreachable"
        detail="The run history could not be loaded."
      />
    );
  }

  return (
    // Asymmetric on purpose: a fixed rail against a fluid workspace, rather
    // than an even split that would read as a dashboard.
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)]">
      <CascadeItem index={0} className="hidden min-h-0 flex-col border-r border-border lg:flex">
        <Panel title="Runs" fill scroll className="border-0" bodyClassName="p-0">
          <RunsRail
            runs={allRuns}
            selectedId={targetId}
            onSelect={(runId) => navigate('overview', { run: runId })}
          />
        </Panel>
      </CascadeItem>

      {/* A flex column, not a plain block: the panels below stretch to the
          bottom of the workspace. Left to their natural height they ended a
          quarter of the way up the viewport, and a terminal with a band of
          empty ground under its instruments reads as broken, not as airy. */}
      <div className="flex min-h-0 min-w-0 flex-col overflow-y-auto">
        {runsStatus === 'loading' ? (
          <EmptyState icon={Hourglass} title="Loading…" role="status" />
        ) : allRuns.length === 0 ? (
          <FirstRun />
        ) : !targetId ? (
          <EmptyState
            icon={FlaskConical}
            title="No completed runs"
            detail="Every recorded run failed. Run a backtest in Strategies to produce a result."
          />
        ) : !run ? (
          <EmptyState icon={Hourglass} title="Loading…" role="status" />
        ) : run.status === 'failed' ? (
          <EmptyState
            testId="overview-run-failed"
            icon={FlaskConical}
            tone="error"
            title="This run failed"
            detail={run.error ?? 'The run did not complete.'}
          />
        ) : performance.status === 'error' ? (
          <EmptyState
            testId="overview-performance-error"
            icon={ServerCrash}
            tone="error"
            title="Could not load performance"
            detail={performance.message}
          />
        ) : performance.status === 'ready' ? (
          <>
            <CascadeItem index={1}>
              <PortfolioSummary run={run} performance={performance.performance} />
            </CascadeItem>

            <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-border xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
              <CascadeItem index={2} className="relative flex min-h-0 flex-col bg-background">
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
                <Panel title="Equity curve" fill className="border-0">
                  <StatRow metrics={performance.performance.metrics} />
                  <FillColumn className="mt-6">
                    <EquityCurve
                      fill
                      equity={performance.performance.equity}
                      benchmark={performance.performance.benchmark}
                      benchmarkLabel="Buy & hold"
                    />
                  </FillColumn>
                  {/* Closed here: the curve is the subject of this screen, and
                      nine lines of prose under it turned the chart into a
                      band. The count in the summary still says they exist. */}
                  <Assumptions
                    assumptions={performance.performance.assumptions}
                    defaultOpen={false}
                  />
                </Panel>
              </CascadeItem>

              <CascadeItem index={3} className="flex min-h-0 flex-col bg-background">
                <Panel
                  title="Open positions"
                  fill
                  scroll
                  className="border-0"
                  bodyClassName="p-0"
                  simulated="The live column re-marks against the simulated feed."
                >
                  <PositionsTable trades={performance.performance.trades} />
                </Panel>
              </CascadeItem>
            </div>
          </>
        ) : (
          <EmptyState icon={Hourglass} title="Loading…" role="status" />
        )}
      </div>
    </div>
  );
}
