import { AlertTriangle, Ban, Hourglass, Info, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import type { Run } from '../api/client';
import type { ExecutionConfig, RunDetailV2 } from '../api/types';
import { FILL_TIMING_SHORT } from '../api/types';
import { navigate } from '../chrome/router';
import { useRunPerformance } from '../quantlab/data/useRunPerformance';
import { EquityCurve } from '../quantlab/charts/EquityCurve';
import { Assumptions } from '../quantlab/panels/Assumptions';
import { BenchmarkPanel } from '../quantlab/panels/BenchmarkPanel';
import { ExitBreakdown } from '../quantlab/panels/ExitBreakdown';
import { StatRow } from '../quantlab/panels/StatRow';
import { TradeLog } from '../quantlab/panels/TradeLog';
import { useRuns } from '../runs/RunsContext';
import { FAILURE_LABELS, pendingDetail } from '../runs/status';
import { Button } from './ui/button';
import { EmptyState } from './ui/empty-state';
import { Input } from './ui/field';
import { Numeric } from './ui/numeric';
import { Panel } from '../quantlab/chrome/Panel';
import { StatusBadge } from './ui/status-badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from './ui/table';

/**
 * Coverage always accompanies a signal count. A count without its denominator
 * is not interpretable: "47 signals" means nothing without knowing how many of
 * the selected instruments actually had data (FR-009).
 */
function Coverage({ run }: { run: Run }) {
  const { instruments_requested, instruments_with_data, instruments_full_warmup } = run.coverage;
  return (
    <dl data-testid="run-coverage" className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      <div className="flex gap-1">
        <dt className="text-muted-foreground">Signals</dt>
        <dd data-testid="signal-count">
          <Numeric value={run.signal_count} format="integer" />
        </dd>
      </div>
      <div className="flex gap-1">
        <dt className="text-muted-foreground">Instruments with data</dt>
        <dd>
          <Numeric value={instruments_with_data} format="integer" />
          <span className="text-muted-foreground">/</span>
          <Numeric value={instruments_requested} format="integer" />
        </dd>
      </div>
      <div className="flex gap-1">
        <dt className="text-muted-foreground">Full warm-up history</dt>
        <dd>
          <Numeric value={instruments_full_warmup} format="integer" />
          <span className="text-muted-foreground">/</span>
          <Numeric value={instruments_requested} format="integer" />
        </dd>
      </div>
      {run.coverage.facts ? (
        <div className="flex gap-1">
          <dt className="text-muted-foreground">With filings</dt>
          <dd data-testid="fact-coverage-count">
            <Numeric value={run.coverage.facts.instruments_with_facts} format="integer" />
            <span className="text-muted-foreground">/</span>
            <Numeric value={instruments_requested} format="integer" />
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

/** How many missing names to list before summarising the rest. */
const MISSING_SHOWN = 8;

/**
 * Names whose fundamental gates could never open. A gate with no filing holds
 * shut and says nothing, so without this a name that never filed revenue reads
 * exactly like one whose revenue never grew.
 */
function FactCoverageWarning({ run }: { run: Run }) {
  const facts = run.coverage.facts;
  if (!facts || facts.instruments_missing_facts.length === 0) return null;
  const requested = run.coverage.instruments_requested;
  const byConcept = Object.entries(facts.missing_by_concept)
    .filter(([, missing]) => missing > 0)
    .map(([concept, missing]) => `${concept} for ${missing} of ${requested}`)
    .join(', ');
  const missing = facts.instruments_missing_facts;
  const shown = missing.slice(0, MISSING_SHOWN).join(', ');
  const rest = missing.length - MISSING_SHOWN;
  return (
    <div
      role="alert"
      data-testid="run-fact-coverage"
      className="mt-3 flex gap-2 rounded-sm border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
    >
      <TriangleAlert size={16} strokeWidth={1.5} className="mt-px shrink-0" />
      <span>
        No filings for {byConcept}. The fundamental gates on {missing.length}{' '}
        {missing.length === 1 ? 'name' : 'names'} never opened, so their silence is missing data,
        not a verdict: {shown}
        {rest > 0 ? ` and ${rest} more` : ''}.
      </span>
    </div>
  );
}

function Provenance({ run }: { run: RunDetailV2 }) {
  return (
    <p className="mt-1 text-xs text-muted-foreground">
      <span
        data-testid="run-dataset"
        className="mr-1 font-mono uppercase tracking-[0.12em] text-foreground"
      >
        {run.dataset === 'warehouse' ? 'live history' : 'demo data'}
      </span>
      · {run.model_name} v{run.model_version} ·{' '}
      <span className="tabular-nums">
        {run.start_date} → {run.end_date}
      </span>{' '}
      ·{' '}
      <span className="font-mono">
        {Object.entries(run.parameters)
          .map(([key, value]) => `${key}=${String(value)}`)
          .join(', ')}
      </span>
    </p>
  );
}

/** Naming a run is what keeps it: saved experiments survive the session. */
function SaveExperiment({ run }: { run: RunDetailV2 }) {
  const { save } = useRuns();
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (run.name) {
    return (
      <StatusBadge tone="good" testId="run-saved-name" title="Saved experiment">
        {run.name}
      </StatusBadge>
    );
  }

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!name.trim() || saving) return;
        setSaving(true);
        setError(null);
        try {
          await save(run.id, name.trim());
        } catch (caught: unknown) {
          setError(caught instanceof Error ? caught.message : 'could not save the run');
        } finally {
          setSaving(false);
        }
      }}
    >
      <Input
        aria-label="Experiment name"
        placeholder="Name this experiment"
        value={name}
        onChange={(event) => setName(event.target.value)}
        className="h-7 w-44"
      />
      <Button type="submit" size="sm" disabled={!name.trim() || saving}>
        {saving ? 'Saving…' : 'Save experiment'}
      </Button>
      {error ? (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      ) : null}
    </form>
  );
}

/**
 * The one results renderer, shared by Research and Strategies: coverage and
 * provenance up front, then what the backend computed — stat row, equity
 * against its benchmark, assumptions, trade log — and the raw signal table.
 *
 * Failed, empty and populated are three visibly different states. A run that
 * found nothing is a result and is not dressed as an error.
 */
export function RunResultsView({ run }: { run: RunDetailV2 }) {
  const performance = useRunPerformance(
    run.status === 'completed' && run.signal_count > 0 ? run.id : null,
  );

  return (
    <div className="h-full overflow-auto" data-testid="run-results">
      <header className="rounded-sm border border-border bg-card p-3">
        <Coverage run={run} />
        <Provenance run={run} />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge tone={run.dataset === 'warehouse' ? 'good' : 'idle'}>
            {run.dataset === 'warehouse' ? 'Live history' : 'Demo data'}
          </StatusBadge>
          {run.re_runnable === false ? (
            <StatusBadge
              tone="bad"
              testId="run-not-rerunnable"
              title="Recorded against a dataset that is not the active one — readable, but not reproducible as recorded."
            >
              Not reproducible
            </StatusBadge>
          ) : null}
          {run.model_available === false ? (
            <StatusBadge
              tone="bad"
              testId="run-model-unavailable"
              title="The recorded model/version is no longer registered; the run stays readable but is not re-runnable."
            >
              Model unavailable
            </StatusBadge>
          ) : null}
          <span className="flex-1" />
          <SaveExperiment run={run} />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => navigate('overview', { run: run.id })}
          >
            Watch in Overview
          </Button>
        </div>
      </header>

      {/* Splits and dividends in the window, and what the run did about them.
          A run stored before adjustment existed traded raw prices: there a
          split breaks the series outright and stays a red correctness warning,
          and a dividend only shaves the price, so it is informational. A run
          that adjusted says so, so the list reads as handled, not as a hazard. */}
      {(() => {
        const actions = run.corporate_actions ?? [];
        const adjustment = run.execution?.price_adjustment ?? 'none';
        const splits = actions.filter((a) => a.action_type === 'split');
        const dividends = actions.filter((a) => a.action_type !== 'split');
        const list = (xs: typeof actions) =>
          xs.map((a) => `${a.symbol} ${a.ex_date}`).join(', ');
        const info =
          'mt-3 flex gap-2 rounded-sm border border-border bg-muted/40 p-2 text-xs text-muted-foreground';
        if (adjustment !== 'none') {
          const handled = adjustment === 'split_dividend' ? dividends : [];
          const ignored = adjustment === 'split' ? dividends : [];
          return (
            <>
              {splits.length > 0 || handled.length > 0 ? (
                <div data-testid="run-corporate-adjustments" className={info}>
                  <Info size={16} strokeWidth={1.5} className="mt-px shrink-0" />
                  <span>
                    {splits.length > 0
                      ? `Adjusted for splits: ${list(splits)}. Signals read split-adjusted prices; shares held were multiplied on each ex-date. `
                      : ''}
                    {handled.length > 0
                      ? `Dividends paid in cash on ${handled.length} ex-date${handled.length === 1 ? '' : 's'}: ${list(handled)}.`
                      : ''}
                  </span>
                </div>
              ) : null}
              {ignored.length > 0 ? (
                <div data-testid="run-dividend-notices" className={info}>
                  <TriangleAlert size={16} strokeWidth={1.5} className="mt-px shrink-0" />
                  <span>
                    Dividend ex-dates in window (not credited — price return only): {list(ignored)}.
                  </span>
                </div>
              ) : null}
            </>
          );
        }
        return (
          <>
            {splits.length > 0 ? (
              <div
                role="alert"
                data-testid="run-corporate-actions"
                className="mt-3 flex gap-2 rounded-sm border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
              >
                <TriangleAlert size={16} strokeWidth={1.5} className="mt-px shrink-0" />
                <span>
                  Unadjusted prices across splits: {list(splits)}. Moves near those dates may be
                  artefacts of the split rather than the market. Re-run with split adjustment to
                  correct it.
                </span>
              </div>
            ) : null}
            {dividends.length > 0 ? (
              <div data-testid="run-dividend-notices" className={info}>
                <TriangleAlert size={16} strokeWidth={1.5} className="mt-px shrink-0" />
                <span>
                  Dividend ex-dates in window (prices unadjusted): {list(dividends)}. Returns near
                  those dates are understated by the payout; tight stops may see spurious dips.
                </span>
              </div>
            ) : null}
          </>
        );
      })()}

      <FactCoverageWarning run={run} />

      {run.strategy ? <StrategyProvenance run={run} /> : null}

      {run.status === 'queued' || run.status === 'running' ? (
        <EmptyState
          testId="run-pending"
          icon={Hourglass}
          role="status"
          title={
            run.status === 'queued'
              ? `Queued${run.queue_position ? ` · #${run.queue_position} in line` : ''}`
              : run.cancel_requested
                ? 'Stopping…'
                : 'Running in the background'
          }
          detail={pendingDetail(run)}
        />
      ) : run.status === 'cancelled' ? (
        <EmptyState
          testId="run-cancelled"
          icon={Ban}
          title="Cancelled"
          detail="This backtest was cancelled before it finished, so it recorded no results. Re-run it from Strategies → Runs."
        />
      ) : run.status === 'failed' ? (
        <EmptyState
          testId="run-failed"
          icon={AlertTriangle}
          tone="error"
          title={
            run.error_category ? `Backtest failed · ${FAILURE_LABELS[run.error_category]}` : 'Backtest failed'
          }
          detail={run.error ?? 'The run did not complete.'}
        />
      ) : run.signal_count === 0 ? (
        // A model finding nothing is a result, not a failure. This state is
        // deliberately styled as an outcome, never as an error (FR-008).
        <EmptyState
          testId="run-empty"
          icon={TriangleAlert}
          title="No signals"
          detail="The model ran and found nothing in this window. That is a result, not a failure — try a wider range or different parameters."
        />
      ) : (
        <>
          {performance.status === 'error' ? (
            <EmptyState
              testId="run-performance-error"
              icon={AlertTriangle}
              tone="error"
              title="Could not load performance"
              detail={performance.message}
            />
          ) : performance.status === 'ready' ? (
            <div className="mt-4 space-y-4">
              <StatRow metrics={performance.performance.metrics} />
              <EquityCurve
                equity={performance.performance.equity}
                benchmark={performance.performance.benchmark}
                benchmarkLabel="Buy & hold"
                height={220}
              />
              {/* Directly under the curve it describes: how much of that line
                  is the benchmark's, and what the timing added. */}
              <BenchmarkPanel regression={performance.performance.regression} />
              {/* Above the trade log, not below it: the assumptions are now
                  derived from the execution criteria this run was actually
                  given, so they are the context the numbers above are read in. */}
              <Assumptions assumptions={performance.performance.assumptions} />
              <ExitBreakdown
                performance={performance.performance}
                summary={run.execution_summary}
              />
              <Panel title="Trade log" bodyClassName="p-0">
                <TradeLog trades={performance.performance.trades} />
              </Panel>
            </div>
          ) : (
            <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              Computing…
            </p>
          )}

          <div className="mt-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Trigger values</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {run.signals.map((signal, index) => (
                  <TableRow key={`${signal.symbol}-${signal.date}-${index}`}>
                    <TableCell className="font-mono text-xs">{signal.symbol}</TableCell>
                    <TableCell className="font-mono text-xs tabular-nums">
                      {signal.date}
                    </TableCell>
                    <TableCell className="text-xs">{signal.direction}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {Object.entries(signal.trigger_values)
                        .map(([key, value]) => `${key}=${String(value)}`)
                        .join(', ')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  );
}

/** The execution fields worth stating on a result, in one line. */
function executionChips(execution: ExecutionConfig): string[] {
  const chips: string[] = [];
  chips.push(FILL_TIMING_SHORT[execution.fill_timing]);
  chips.push(`${execution.position_sizing.replace(/_/g, ' ')} sizing`);
  if (execution.max_positions !== null) chips.push(`max ${execution.max_positions} positions`);
  if (execution.commission_bps > 0) chips.push(`${execution.commission_bps} bps commission`);
  if (execution.slippage_bps > 0) chips.push(`${execution.slippage_bps} bps slippage`);
  if (execution.stop_loss_pct !== null) chips.push(`${execution.stop_loss_pct * 100}% stop`);
  if (execution.take_profit_pct !== null) chips.push(`${execution.take_profit_pct * 100}% target`);
  if (execution.trailing_stop_pct !== null) {
    chips.push(`${execution.trailing_stop_pct * 100}% trailing stop`);
  }
  if (execution.max_holding_days !== null) chips.push(`${execution.max_holding_days} bar max hold`);
  if (execution.cooldown_days > 0) chips.push(`${execution.cooldown_days} bar cooldown`);
  chips.push(execution.allow_shorts ? 'shorts allowed' : 'long only');
  return chips;
}

/**
 * The composed strategy the run actually executed.
 *
 * Read from the run's own `strategy` and `execution` -- the fully resolved
 * spec, per the contract -- and never from whatever is currently in the
 * builder. A result has to describe the thing that produced it, including
 * after the builder has moved on to the next idea.
 */
function StrategyProvenance({ run }: { run: RunDetailV2 }) {
  const strategy = run.strategy;
  if (!strategy) return null;
  const execution = run.execution ?? null;

  return (
    <section
      data-testid="run-strategy"
      aria-label="Strategy executed"
      className="mt-3 border border-border bg-card p-3"
    >
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        Strategy executed
      </p>
      <p className="mt-1 text-xs">{strategy.name}</p>
      <ul className="mt-2 space-y-1">
        {strategy.components.map((component, index) => (
          <li
            key={`${component.rule_name}-${component.role}-${index}`}
            className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
          >
            <StatusBadge tone={component.role === 'entry' ? 'active' : 'idle'}>
              {component.role}
            </StatusBadge>
            <span className="font-mono">{component.rule_name}</span>
            <span className="font-mono tabular-nums">
              {Object.entries(component.parameters ?? {})
                .map(([key, value]) => `${key}=${String(value)}`)
                .join(', ')}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted-foreground">
        <span className="font-mono uppercase tracking-[0.12em]">{strategy.entry_logic}</span> to
        enter,{' '}
        <span className="font-mono uppercase tracking-[0.12em]">{strategy.exit_logic}</span> to
        exit, agreement window{' '}
        <span className="font-mono tabular-nums">{strategy.combine_window_days}</span>
      </p>
      {execution ? (
        <p data-testid="run-execution" className="mt-1 text-xs text-muted-foreground">
          {executionChips(execution as ExecutionConfig).join(' \u00b7 ')}
        </p>
      ) : null}
    </section>
  );
}
