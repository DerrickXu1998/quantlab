import type { Run, RunDetail } from '../api/client';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { useWorkbench } from './WorkbenchContext';

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
        <dd data-testid="signal-count" className="font-semibold tabular-nums">
          {run.signal_count}
        </dd>
      </div>
      <div className="flex gap-1">
        <dt className="text-muted-foreground">Instruments with data</dt>
        <dd className="tabular-nums">
          {instruments_with_data}/{instruments_requested}
        </dd>
      </div>
      <div className="flex gap-1">
        <dt className="text-muted-foreground">Full warm-up history</dt>
        <dd className="tabular-nums">
          {instruments_full_warmup}/{instruments_requested}
        </dd>
      </div>
    </dl>
  );
}

function Provenance({ run }: { run: RunDetail }) {
  return (
    <p className="mt-1 text-xs text-muted-foreground">
      {run.model_name} v{run.model_version} · {run.start_date} → {run.end_date} ·{' '}
      <span className="font-mono">
        {Object.entries(run.parameters)
          .map(([key, value]) => `${key}=${String(value)}`)
          .join(', ')}
      </span>
    </p>
  );
}

export function RunResults() {
  const { runs } = useWorkbench();
  const run = runs.activeRun;

  if (!run) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        Configure a model and run it to see results here.
      </div>
    );
  }

  if (run.status === 'failed') {
    return (
      <div className="h-full overflow-auto p-3">
        <div
          role="alert"
          data-testid="run-failed"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          <strong>The run failed.</strong> {run.error}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-3" data-testid="run-results">
      <header className="mb-3 rounded-lg border border-border bg-card p-3">
        <Coverage run={run} />
        <Provenance run={run} />
      </header>

      {run.signal_count === 0 ? (
        // A model finding nothing is a result, not a failure. This state is
        // deliberately styled as an outcome, never as an error (FR-008).
        <div
          data-testid="run-empty"
          className="rounded-lg border border-border bg-muted px-6 py-8 text-center text-sm text-muted-foreground"
        >
          This model produced <strong>no signals</strong> over the selected dataset. The run
          completed successfully — that is a result, not an error.
        </div>
      ) : (
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
                <TableCell className="font-medium">{signal.symbol}</TableCell>
                <TableCell className="tabular-nums">{signal.date}</TableCell>
                <TableCell>{signal.direction}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {Object.entries(signal.trigger_values)
                    .map(([key, value]) => `${key}=${String(value)}`)
                    .join(', ')}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
