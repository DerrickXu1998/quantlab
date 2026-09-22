import { AlertTriangle, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import type { Run } from '../api/client';
import type { ExecutionConfig, RunDetailV2 } from '../api/types';
import { navigate } from '../chrome/router';
import { useRunPerformance } from '../quantlab/data/useRunPerformance';
import { EquityCurve } from '../quantlab/charts/EquityCurve';
import { Assumptions } from '../quantlab/panels/Assumptions';
import { ExitBreakdown } from '../quantlab/panels/ExitBreakdown';
import { StatRow } from '../quantlab/panels/StatRow';
import { TradeLog } from '../quantlab/panels/TradeLog';
import { useRuns } from '../runs/RunsContext';
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
    </dl>
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
        <span role="alert" className="text-[11px] text-destructive">
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

      {/* A correctness warning, not a footnote: stored bars are unadjusted, so
          any signal near an ex-date may be an artefact of the split rather
          than a market move. */}
      {(run.corporate_actions ?? []).length > 0 ? (
        <div
          role="alert"
          data-testid="run-corporate-actions"
          className="mt-3 flex gap-2 rounded-sm border border-destructive/40 bg-destructive/5 p-2 text-[11px] text-destructive"
        >
          <TriangleAlert size={16} strokeWidth={1.5} className="mt-px shrink-0" />
          <span>
            Unadjusted prices across{' '}
            {(run.corporate_actions ?? [])
              .map((action) => `${action.symbol} ${action.ex_date}`)
              .join(', ')}
            . Moves near those dates may be artefacts of the action rather than the market.
          </span>
        </div>
      ) : null}

      {run.strategy ? <StrategyProvenance run={run} /> : null}

      {run.status === 'failed' ? (
        <EmptyState
          testId="run-failed"
          icon={AlertTriangle}
          tone="error"
          title="Backtest failed"
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
  chips.push(execution.fill_timing === 'next_open' ? 'fills next open' : 'fills at signal close');
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
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        Strategy executed
      </p>
      <p className="mt-1 text-xs">{strategy.name}</p>
      <ul className="mt-2 space-y-1">
        {strategy.components.map((component, index) => (
          <li
            key={`${component.rule_name}-${component.role}-${index}`}
            className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground"
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
      <p className="mt-2 text-[11px] text-muted-foreground">
        <span className="font-mono uppercase tracking-[0.12em]">{strategy.entry_logic}</span> to
        enter,{' '}
        <span className="font-mono uppercase tracking-[0.12em]">{strategy.exit_logic}</span> to
        exit, agreement window{' '}
        <span className="font-mono tabular-nums">{strategy.combine_window_days}</span>
      </p>
      {execution ? (
        <p data-testid="run-execution" className="mt-1 text-[11px] text-muted-foreground">
          {executionChips(execution).join(' \u00b7 ')}
        </p>
      ) : null}
    </section>
  );
}
