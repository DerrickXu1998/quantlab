import { AlertTriangle, TriangleAlert } from 'lucide-react';
import type { RunDetail, RunPerformance } from '../../api/client';
import { EquityCurve } from '../charts/EquityCurve';
import { EmptyState } from '../chrome/EmptyState';
import { Numeric } from '../chrome/Numeric';
import { StatusBadge } from '../chrome/StatusBadge';
import { Assumptions } from './Assumptions';
import { StatRow } from './StatRow';

function Coverage({ run }: { run: RunDetail }) {
  const { coverage } = run;
  return (
    <div
      data-testid="lab-run-coverage"
      className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-muted-foreground"
    >
      <span className="flex items-center gap-1.5">
        signals
        <Numeric value={run.signal_count} format="integer" tone="accent" />
      </span>
      <span className="flex items-center gap-1.5" title="Instruments that had any bars in the window">
        with data
        <span className="font-mono tabular-nums">
          {coverage.instruments_with_data}/{coverage.instruments_requested}
        </span>
      </span>
      <span
        className="flex items-center gap-1.5"
        title="Instruments with enough history before the window to satisfy the model's lookback"
      >
        full warm-up
        <span className="font-mono tabular-nums">
          {coverage.instruments_full_warmup}/{coverage.instruments_requested}
        </span>
      </span>
      <StatusBadge tone={run.dataset === 'warehouse' ? 'good' : 'idle'}>
        {run.dataset === 'warehouse' ? 'Live history' : 'Demo data'}
      </StatusBadge>
      {run.re_runnable ? null : (
        <StatusBadge tone="bad" title="Recorded against a dataset that is not the active one.">
          Not reproducible
        </StatusBadge>
      )}
    </div>
  );
}

/**
 * The outcome of a backtest: what the run reported, plus what the backend
 * computed from it.
 *
 * Failed, empty and populated are three visibly different states. A run that
 * found nothing is a result and is not dressed as an error.
 */
export function BacktestResults({
  run,
  performance,
  performanceError,
}: {
  run: RunDetail;
  performance: RunPerformance | null;
  performanceError: string | null;
}) {
  if (run.status === 'failed') {
    return (
      <EmptyState
        testId="lab-run-failed"
        icon={AlertTriangle}
        tone="error"
        title="Backtest failed"
        detail={run.error ?? 'The run did not complete.'}
      />
    );
  }

  return (
    <div className="space-y-5">
      <Coverage run={run} />

      {(run.corporate_actions ?? []).length > 0 ? (
        <div
          role="alert"
          data-testid="lab-corporate-actions"
          className="flex gap-2 border border-destructive/40 bg-destructive/5 p-2 text-[11px] text-destructive"
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

      {run.signal_count === 0 ? (
        <EmptyState
          testId="lab-run-empty"
          icon={TriangleAlert}
          title="No signals"
          detail="The model ran and found nothing in this window. That is a result, not a failure — try a wider range or different parameters."
        />
      ) : performanceError ? (
        <EmptyState
          testId="lab-performance-error"
          icon={AlertTriangle}
          tone="error"
          title="Could not load performance"
          detail={performanceError}
        />
      ) : performance ? (
        <>
          <StatRow metrics={performance.metrics} />
          <EquityCurve
            equity={performance.equity}
            benchmark={performance.benchmark}
            benchmarkLabel="Buy & hold"
            height={220}
          />
          <Assumptions assumptions={performance.assumptions} />
        </>
      ) : (
        <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          Computing…
        </p>
      )}
    </div>
  );
}
