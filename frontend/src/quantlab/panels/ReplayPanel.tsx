import {
  ChartLine,
  Hourglass,
  Pause,
  Play,
  RotateCcw,
  ServerCrash,
  TriangleAlert,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import type { Run } from '../../api/client';
import { Button } from '../../components/ui/button';
import { ButtonGroup, FillColumn, StatGrid } from '../../components/ui/layout';
import { EmptyState } from '../chrome/EmptyState';
import { Numeric } from '../chrome/Numeric';
import { Panel } from '../chrome/Panel';
import { StatusBadge } from '../chrome/StatusBadge';
import { EquityCurve } from '../charts/EquityCurve';
import { useReplay, type ReplayStatus } from '../data/useReplay';
import { Assumptions } from './Assumptions';
import { StatRow } from './StatRow';

/** Pacing presets, as the interval_ms the backend sleeps between days. */
const SPEEDS: { label: string; intervalMs: number }[] = [
  { label: 'Fast', intervalMs: 0 },
  { label: '25 ms', intervalMs: 25 },
  { label: '50 ms', intervalMs: 50 },
  { label: '100 ms', intervalMs: 100 },
];

const STATUS_LABEL: Record<ReplayStatus, string> = {
  idle: 'Idle',
  connecting: 'Connecting',
  streaming: 'Streaming',
  paused: 'Paused',
  done: 'Complete',
  truncated: 'Truncated',
  error: 'Error',
};

function runLabel(run: Run): string {
  return `${run.name ?? run.model_name} · ${run.start_date} → ${run.end_date}`;
}

/** Progress along the window's calendar — a position indicator, not a metric. */
function progressPercent(current: string | null, run: Run): number | null {
  if (!current) return null;
  const start = Date.parse(run.start_date);
  const end = Date.parse(run.end_date);
  const now = Date.parse(current);
  if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(now) || end <= start) {
    return null;
  }
  return Math.min(100, Math.max(0, ((now - start) / (end - start)) * 100));
}

function BookStat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      <span className="text-sm">{children}</span>
    </div>
  );
}

/**
 * The book's five figures.
 *
 * `StatGrid` rather than a five-column grid: across a 1100px panel the fixed
 * columns were 220px each and every label sat a hand's width from its number.
 * The grid packs them at a readable density and wraps instead of stretching.
 */
function BookStats({ state }: { state: ReturnType<typeof useReplay>['state'] }) {
  const now = state.equityNow;
  return (
    <div data-testid="replay-stats">
      <StatGrid min="8rem">
        <BookStat label="Date">
          <span className="font-mono tabular-nums">{state.currentDate ?? '—'}</span>
        </BookStat>
        <BookStat label="Equity">
          <Numeric value={now?.equity ?? null} format="currency" />
        </BookStat>
        <BookStat label="Cash">
          <Numeric value={now?.cash ?? null} format="currency" />
        </BookStat>
        <BookStat label="Open positions">
          <Numeric value={now?.positions ?? null} format="integer" />
        </BookStat>
        <BookStat label="Realized P&L">
          <Numeric value={now?.realizedPnl ?? null} format="signedPrice" tone="signed" />
        </BookStat>
      </StatGrid>
    </div>
  );
}

/**
 * One run's history replayed as it happened. Every number on screen arrived
 * as a server-computed event — the panel renders the stream and computes
 * nothing itself (Constitution V).
 */
export function ReplayPanel({ runs }: { runs: Run[] }) {
  const completed = runs.filter((run) => run.status === 'completed');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [speed, setSpeed] = useState(50);
  const run = completed.find((candidate) => candidate.id === selectedId) ?? completed[0] ?? null;
  const { state, play, pause, restart } = useReplay(run?.id ?? null, speed);

  if (completed.length === 0) {
    return (
      <EmptyState
        className="min-h-0 flex-1"
        testId="replay-no-runs"
        icon={Hourglass}
        title="No completed runs"
        detail="Run a backtest in Strategies first — a replay needs a completed run to walk through."
      />
    );
  }

  const playing = state.status === 'streaming' || state.status === 'connecting';
  const finished = state.status === 'done' || state.status === 'truncated';
  const percent = run ? progressPercent(state.currentDate, run) : null;

  return (
    <div
      data-testid="replay-panel"
      // Two filling columns on a desktop; stacked and scrolled below that. The
      // grid's single row takes the workspace height, so both columns are as
      // tall as the screen and neither leaves a band of dead ground beneath it.
      className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 lg:grid-cols-[300px_minmax(0,1fr)] lg:overflow-hidden"
    >
      <Panel title="Replay" fill scroll bodyClassName="flex flex-col gap-4 p-3">
        <label className="flex flex-col gap-1.5">
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            Run
          </span>
          <select
            data-testid="replay-run-select"
            className="h-8 rounded-sm border border-border bg-card px-2 font-mono text-[11px]"
            value={run?.id ?? ''}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            {completed.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {runLabel(candidate)}
              </option>
            ))}
          </select>
        </label>

        <fieldset
          className="flex flex-col gap-1.5"
          title="Applies from the next play; a running stream keeps its pace."
        >
          <legend className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            Speed
          </legend>
          {/* One control, not two: the group wraps as a unit rather than
              orphaning `100 ms` onto a line of its own. */}
          <ButtonGroup label="Replay speed">
            {SPEEDS.map((preset) => (
              <Button
                key={preset.intervalMs}
                type="button"
                size="sm"
                variant={speed === preset.intervalMs ? 'default' : 'outline'}
                aria-pressed={speed === preset.intervalMs}
                onClick={() => setSpeed(preset.intervalMs)}
              >
                {preset.label}
              </Button>
            ))}
          </ButtonGroup>
        </fieldset>

        <div className="flex items-center gap-2">
          {playing ? (
            <Button type="button" size="sm" onClick={pause}>
              <Pause size={16} strokeWidth={1.5} aria-hidden="true" />
              Pause
            </Button>
          ) : (
            <Button type="button" size="sm" onClick={play} disabled={!run}>
              <Play size={16} strokeWidth={1.5} aria-hidden="true" />
              {state.status === 'paused'
                ? 'Resume'
                : finished || state.status === 'error'
                  ? 'Replay'
                  : 'Play'}
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={restart}
            disabled={state.status === 'idle'}
          >
            <RotateCcw size={16} strokeWidth={1.5} aria-hidden="true" />
            Reset
          </Button>
          <StatusBadge
            tone={
              state.status === 'error' || state.status === 'truncated'
                ? 'bad'
                : playing
                  ? 'active'
                  : 'idle'
            }
            testId="replay-status"
          >
            {STATUS_LABEL[state.status]}
          </StatusBadge>
        </div>

        {run ? (
          // Anchored to the foot of the column: the controls are what you
          // reach for, the progress readout is what you glance at, and the
          // panel now fills its cell rather than floating above empty ground.
          <div className="mt-auto flex flex-col gap-1">
            <div
              role="progressbar"
              data-testid="replay-progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent === null ? undefined : Math.round(percent)}
              aria-label="Replay progress"
              className="h-1 w-full overflow-hidden rounded-sm bg-border"
            >
              <div className="h-full bg-primary" style={{ width: `${percent ?? 0}%` }} />
            </div>
            <p className="font-mono text-[10px] text-muted-foreground">
              {state.currentDate ?? '—'} of {run.start_date} → {run.end_date}
            </p>
            {state.status === 'paused' ? (
              <p className="text-[11px] text-muted-foreground">
                Paused freezes the display, not the stream — queued events render together on
                resume.
              </p>
            ) : null}
          </div>
        ) : null}
      </Panel>

      {/* The workspace column: Book keeps its natural height, Equity and the
          fill/signal tables share the slack, and the column scrolls only when
          those floors genuinely no longer fit. */}
      <FillColumn className="min-w-0 gap-4 overflow-y-auto">
        {state.status === 'error' ? (
          <EmptyState
            className="shrink-0"
            testId="replay-error"
            icon={ServerCrash}
            tone="error"
            title="Replay stream failed"
            detail={state.error ?? undefined}
          />
        ) : null}
        {state.status === 'truncated' ? (
          <div
            role="alert"
            data-testid="replay-truncated"
            className="flex shrink-0 gap-2 rounded-sm border border-destructive/40 bg-destructive/5 p-2 text-[11px] text-destructive"
          >
            <TriangleAlert size={16} strokeWidth={1.5} className="mt-px shrink-0" />
            <span>
              The stream hit its event cap before finishing ({state.truncation}). What is shown is a
              prefix of the run, not its result.
            </span>
          </div>
        ) : null}

        <Panel title="Book" className="shrink-0" bodyClassName="p-3">
          <BookStats state={state} />
          {Object.keys(state.closes).length > 0 ? (
            <p
              data-testid="replay-prices"
              className="mt-3 font-mono text-[11px] text-muted-foreground"
            >
              {Object.entries(state.closes)
                .map(([symbol, price]) => `${symbol} ${price.toFixed(2)}`)
                .join(' · ')}
            </p>
          ) : null}
        </Panel>

        <Panel title="Equity" fill className="min-h-[220px] flex-[2]" bodyClassName="p-3">
          {state.equity.length === 0 ? (
            <EmptyState
              className="min-h-0 flex-1"
              testId="replay-equity-empty"
              icon={ChartLine}
              title="No equity yet"
              detail="Press Play and the run's equity curve is drawn here, one session at a time."
            />
          ) : (
            <EquityCurve equity={state.equity} strategyLabel="Replayed equity" fill />
          )}
        </Panel>

        <div className="grid min-h-[168px] flex-[1] grid-cols-1 gap-4 xl:grid-cols-2">
          <Panel
            title="Fills"
            fill
            scroll
            bodyClassName="p-0"
            actions={
              <span className="font-mono text-[10px] text-muted-foreground">
                {state.fills.length > 0 ? `latest ${state.fills.length}` : ''}
              </span>
            }
          >
            {state.fills.length === 0 ? (
              <p className="p-3 font-mono text-[11px] text-muted-foreground">No fills yet.</p>
            ) : (
              <table data-testid="replay-fills" className="w-full">
                <thead className="sticky top-0 bg-card">
                  <tr className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    <th className="px-3 py-1.5 text-left font-normal">Date</th>
                    <th className="px-3 py-1.5 text-left font-normal">Symbol</th>
                    <th className="px-3 py-1.5 text-left font-normal">Side</th>
                    <th className="px-3 py-1.5 text-right font-normal">Qty</th>
                    <th className="px-3 py-1.5 text-right font-normal">Price</th>
                  </tr>
                </thead>
                <tbody>
                  {state.fills.map((fill, index) => (
                    <tr
                      key={`${fill.date}-${fill.symbol}-${index}`}
                      className="border-t border-border"
                    >
                      <td className="px-3 py-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                        {fill.date}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-[11px]">{fill.symbol}</td>
                      <td className="px-3 py-1.5">
                        <StatusBadge tone={fill.side === 'buy' ? 'active' : 'idle'}>
                          {fill.side}
                        </StatusBadge>
                      </td>
                      <td className="px-3 py-1.5 text-right">
                        <Numeric value={fill.qty} format="price" className="text-[11px]" />
                      </td>
                      <td className="px-3 py-1.5 text-right">
                        <Numeric value={fill.price} format="price" className="text-[11px]" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          <Panel title="Signals" fill scroll bodyClassName="p-0">
            {state.signals.length === 0 ? (
              <p className="p-3 font-mono text-[11px] text-muted-foreground">No signals yet.</p>
            ) : (
              <table data-testid="replay-signals" className="w-full">
                <thead className="sticky top-0 bg-card">
                  <tr className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    <th className="px-3 py-1.5 text-left font-normal">Date</th>
                    <th className="px-3 py-1.5 text-left font-normal">Symbol</th>
                    <th className="px-3 py-1.5 text-left font-normal">Direction</th>
                    <th className="px-3 py-1.5 text-left font-normal">Trigger values</th>
                  </tr>
                </thead>
                <tbody>
                  {state.signals.map((signal, index) => (
                    <tr
                      key={`${signal.date}-${signal.symbol}-${index}`}
                      className="border-t border-border"
                    >
                      <td className="px-3 py-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                        {signal.date}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-[11px]">{signal.symbol}</td>
                      <td className="px-3 py-1.5">
                        <StatusBadge tone={signal.direction === 'bullish' ? 'active' : 'idle'}>
                          {signal.direction}
                        </StatusBadge>
                      </td>
                      <td className="px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
                        {Object.entries(signal.trigger_values)
                          .map(([key, value]) => `${key}=${String(value)}`)
                          .join(', ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>

        {state.summary ? (
          <Panel title="Replay summary" className="shrink-0 border-primary/40" bodyClassName="p-3">
            <div data-testid="replay-summary" className="space-y-4">
              <StatRow metrics={state.summary} />
              <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                <div className="flex gap-1">
                  <dt className="text-muted-foreground">Days</dt>
                  <dd>
                    <Numeric value={state.summary.days} format="integer" />
                  </dd>
                </div>
                <div className="flex gap-1">
                  <dt className="text-muted-foreground">Trades</dt>
                  <dd>
                    <Numeric value={state.summary.trade_count} format="integer" />(
                    <Numeric value={state.summary.winning_trades} format="integer" /> won /{' '}
                    <Numeric value={state.summary.losing_trades} format="integer" /> lost)
                  </dd>
                </div>
                <div className="flex gap-1">
                  <dt className="text-muted-foreground">Equity</dt>
                  <dd>
                    <Numeric value={state.summary.initial_cash} format="currency" /> →{' '}
                    <Numeric value={state.summary.final_equity} format="currency" />
                  </dd>
                </div>
              </dl>
              <Assumptions assumptions={state.summary.assumptions} />
            </div>
          </Panel>
        ) : null}
      </FillColumn>
    </div>
  );
}
