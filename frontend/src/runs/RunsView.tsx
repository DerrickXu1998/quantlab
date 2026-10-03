import {
  ArrowLeft,
  Ban,
  Copy,
  FlaskConical,
  Hourglass,
  RotateCcw,
  ServerCrash,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { isActiveRun } from '../api/client';
import type { RunDetailV2, RunV2 } from '../api/types';
import { ConfirmDelete } from '../components/ConfirmDelete';
import { RunResultsView } from '../components/RunResultsView';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { Select } from '../components/ui/field';
import { Numeric } from '../components/ui/numeric';
import { StatusBadge } from '../components/ui/status-badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { Panel } from '../quantlab/chrome/Panel';
import { BAR_FREQUENCY_LABELS, type BarFrequency } from '../strategies/barFrequency';
import { GlossaryFrequency, Term } from '../glossary/Term';
import { runDisplayName } from './labels';
import { Sparkline } from './Sparkline';
import { useRuns } from './RunsContext';
import {
  componentCount,
  durationBetween,
  expectedDuration,
  FAILURE_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
  statusLabel,
  type RunStatus,
} from './status';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

/** What "Clone to editor" hands Configure: a run's recorded configuration. */
export interface RunClone {
  key: string;
  run: RunV2;
}

type StatusFilter = 'all' | 'active' | RunStatus;

function barsOf(run: RunV2): BarFrequency {
  return ((run.execution?.bar_frequency as BarFrequency | undefined) ?? '1d') as BarFrequency;
}

function submittedAt(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const today = new Date();
  const sameDay = when.toDateString() === today.toDateString();
  return sameDay
    ? when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : when.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function durationCell(run: RunV2): string {
  const components = componentCount(run);
  if (run.status === 'queued') {
    const expected = expectedDuration(run.estimated_bars, components);
    return expected ? `~${expected}` : '—';
  }
  if (run.status === 'running') {
    const expected = expectedDuration(run.estimated_bars, components);
    return expected ? `running · ~${expected}` : 'running';
  }
  return durationBetween(run.started_at, run.finished_at) ?? '—';
}

/**
 * Runs: every backtest, its status and its headline numbers.
 *
 * A run opens as a full page rather than beside the table: the table needs its
 * columns and the results need the width for their charts. Results are stored
 * when a run completes, so opening one is a read, not a wait.
 */
export function RunsView({
  runId,
  onOpen,
  onBack,
  onClone,
}: {
  runId: string | null;
  onOpen: (runId: string) => void;
  onBack: () => void;
  onClone: (clone: RunClone) => void;
}) {
  return runId ? (
    <RunDetail runId={runId} onBack={onBack} onClone={onClone} onOpen={onOpen} />
  ) : (
    <RunsTable onOpen={onOpen} onClone={onClone} />
  );
}

/** A run whose results the worker has not stored yet (an older run). */
function awaitingResults(run: RunV2): boolean {
  return run.status === 'completed' && !run.metrics && !run.results_error;
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/**
 * Across the runs shown: how many have results, how many beat buy-and-hold of
 * their own selection, the best of them, and the typical Sharpe and excess
 * return. Read from each run's stored summary; nothing here touches a bar.
 */
function RunsAggregate({ rows }: { rows: RunV2[] }) {
  const scored = rows.filter((run) => run.status === 'completed' && run.metrics);
  const pending = rows.filter(awaitingResults).length;
  if (scored.length === 0 && pending === 0) return null;
  const excess = scored
    .map((run) => run.summary?.excess_return)
    .filter((value): value is number => typeof value === 'number');
  const beat = excess.filter((value) => value > 0).length;
  const best = scored.reduce<RunV2 | null>(
    (top, run) =>
      !top || (run.metrics?.total_return ?? -Infinity) > (top.metrics?.total_return ?? -Infinity)
        ? run
        : top,
    null,
  );
  const sharpe = median(
    scored
      .map((run) => run.metrics?.sharpe_ratio)
      .filter((value): value is number => typeof value === 'number'),
  );
  const cell = 'space-y-1 border-l border-border px-3 first:border-l-0 first:pl-0';
  return (
    <dl
      data-testid="runs-aggregate"
      className="flex flex-wrap gap-y-2 border border-border bg-card px-3 py-2"
    >
      <div className={cell}>
        <dt className={MICRO}>With results</dt>
        <dd className="font-mono text-sm tabular-nums">
          {scored.length}
          {pending > 0 ? (
            <span className="ml-2 text-xs text-muted-foreground">+{pending} preparing</span>
          ) : null}
        </dd>
      </div>
      <div className={cell}>
        <dt className={MICRO}>
          <Term id="benchmark">Beat buy &amp; hold</Term>
        </dt>
        <dd className="font-mono text-sm tabular-nums">
          {excess.length > 0 ? `${beat} of ${excess.length}` : '—'}
        </dd>
      </div>
      <div className={cell}>
        <dt className={MICRO}>
          <Term id="excess_return">Median excess vs B&amp;H</Term>
        </dt>
        <dd className="text-sm">
          <Numeric value={median(excess)} format="signedPercent" tone="signed" />
        </dd>
      </div>
      <div className={cell}>
        <dt className={MICRO}>
          <Term id="sharpe">Median Sharpe</Term>
        </dt>
        <dd className="text-sm">
          <Numeric value={sharpe} format="ratio" />
        </dd>
      </div>
      <div className={cell}>
        <dt className={MICRO}>
          <Term id="total_return">Best return</Term>
        </dt>
        <dd className="flex items-baseline gap-2 text-sm">
          <Numeric
            value={best?.metrics?.total_return ?? null}
            format="signedPercent"
            tone="signed"
          />
          {best ? (
            <span className="max-w-[12rem] truncate text-xs text-muted-foreground">
              {runDisplayName(best)}
            </span>
          ) : null}
        </dd>
      </div>
    </dl>
  );
}

function RunsTable({
  onOpen,
  onClone,
}: {
  onOpen: (runId: string) => void;
  onClone: (clone: RunClone) => void;
}) {
  const { allRuns, runsStatus, reloadRuns, cancelRun, remove, submitStrategyRun } = useRuns();
  const [status, setStatus] = useState<StatusFilter>('all');
  const [bars, setBars] = useState<'any' | BarFrequency>('any');
  const [savedOnly, setSavedOnly] = useState(false);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return allRuns.filter((run) => {
      if (status === 'active' && !isActiveRun(run)) return false;
      if (status !== 'all' && status !== 'active' && run.status !== status) return false;
      if (bars !== 'any' && barsOf(run) !== bars) return false;
      if (savedOnly && !run.name) return false;
      if (needle) {
        const haystack = `${runDisplayName(run)} ${run.symbols.join(' ')}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [allRuns, status, bars, savedOnly, query]);

  // Selection follows the rows: a run filtered away or deleted is deselected.
  useEffect(() => {
    setSelected((current) => {
      const visible = new Set(rows.map((run) => run.id));
      const next = new Set([...current].filter((id) => visible.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [rows]);

  const chosen = rows.filter((run) => selected.has(run.id));
  const cancellable = chosen.filter(isActiveRun);
  const activeCount = allRuns.filter(isActiveRun).length;
  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const act = async (work: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await work();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'that did not work');
    }
  };

  const rerun = (run: RunV2) =>
    act(async () => {
      if (!run.strategy) throw new Error('this run has no recorded strategy to run again');
      await submitStrategyRun({
        strategy: run.strategy,
        symbols: run.symbols,
        start_date: run.start_date,
        end_date: run.end_date,
      });
    });

  if (runsStatus === 'loading' && allRuns.length === 0) {
    return <EmptyState icon={Hourglass} title="Loading runs…" role="status" />;
  }
  if (runsStatus === 'error' && allRuns.length === 0) {
    return (
      <EmptyState
        testId="runs-error"
        icon={ServerCrash}
        tone="error"
        title="Could not load your runs"
        action={
          <Button type="button" size="sm" variant="outline" onClick={reloadRuns}>
            Try again
          </Button>
        }
      />
    );
  }
  if (allRuns.length === 0) {
    return (
      <EmptyState
        testId="runs-empty"
        icon={FlaskConical}
        title="No backtests yet"
        detail="Build a strategy in Configure and submit it. It runs in the background and appears here with its status and results."
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 p-4" data-testid="runs-table-view">
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1">
          <span className={MICRO}>Status</span>
          <Select
            value={status}
            onChange={(event) => setStatus(event.target.value as StatusFilter)}
          >
            <option value="all">All</option>
            <option value="active">Queued or running</option>
            {(Object.keys(STATUS_LABELS) as RunStatus[]).map((value) => (
              <option key={value} value={value}>
                {STATUS_LABELS[value]}
              </option>
            ))}
          </Select>
        </label>
        <label className="space-y-1">
          <span className={MICRO}>Bars</span>
          <Select
            value={bars}
            onChange={(event) => setBars(event.target.value as 'any' | BarFrequency)}
          >
            <option value="any">Any</option>
            {(Object.keys(BAR_FREQUENCY_LABELS) as BarFrequency[]).map((value) => (
              <option key={value} value={value}>
                {BAR_FREQUENCY_LABELS[value]}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex h-9 items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={savedOnly}
            onChange={(event) => setSavedOnly(event.target.checked)}
          />
          Saved only
        </label>
        <label className="min-w-[10rem] flex-1 space-y-1 sm:max-w-xs">
          <span className={MICRO}>Search</span>
          <input
            type="search"
            aria-label="Search runs by name or ticker"
            placeholder="Name or ticker"
            className="h-9 w-full rounded-sm border border-border bg-card px-2 font-mono text-[11px] focus-visible:border-primary focus-visible:outline-none"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <span className="flex-1" />
        <p className={MICRO} aria-live="polite">
          <span className="tabular-nums">{rows.length}</span> of{' '}
          <span className="tabular-nums">{allRuns.length}</span> runs
          {activeCount > 0 ? (
            <>
              {' '}
              · <span className="tabular-nums">{activeCount}</span> active
            </>
          ) : null}
        </p>
      </div>

      {chosen.length > 0 ? (
        <div
          data-testid="runs-selection"
          className="flex flex-wrap items-center gap-2 border border-border bg-card px-3 py-2 text-xs"
        >
          <span className={MICRO}>
            <span className="tabular-nums">{chosen.length}</span> selected
          </span>
          {cancellable.length > 0 ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => act(() => Promise.all(cancellable.map((run) => cancelRun(run.id))))}
            >
              Cancel {cancellable.length}
            </Button>
          ) : null}
          <ConfirmDelete
            label={`Delete ${chosen.length} selected run${chosen.length === 1 ? '' : 's'}`}
            title="Delete runs"
            variant="outline"
            onConfirm={() => act(() => Promise.all(chosen.map((run) => remove(run.id))))}
          >
            Delete {chosen.length}
          </ConfirmDelete>
          <Button type="button" size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      ) : null}

      {actionError ? (
        <p role="alert" className="text-xs text-destructive">
          {actionError}
        </p>
      ) : null}

      {rows.length > 0 ? <RunsAggregate rows={rows} /> : null}

      {rows.length === 0 ? (
        <EmptyState
          testId="runs-filtered-empty"
          icon={FlaskConical}
          title="No runs match"
          action={
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setStatus('all');
                setBars('any');
                setSavedOnly(false);
                setQuery('');
              }}
            >
              Clear filters
            </Button>
          }
        />
      ) : (
        <Panel title="Backtests" fill scroll bodyClassName="p-0">
          <div className="overflow-x-auto">
            <Table data-testid="runs-table">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">
                    <input
                      type="checkbox"
                      aria-label="Select every run shown"
                      checked={chosen.length === rows.length}
                      onChange={(event) =>
                        setSelected(
                          event.target.checked ? new Set(rows.map((run) => run.id)) : new Set(),
                        )
                      }
                    />
                  </TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>
                    <Term id="bar_frequency">Bars</Term>
                  </TableHead>
                  <TableHead>
                    <Term id="universe">Universe</Term>
                  </TableHead>
                  <TableHead>Window</TableHead>
                  <TableHead>Submitted</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead className="text-right">
                    <Term id="total_return">Return</Term>
                  </TableHead>
                  <TableHead className="text-right">
                    <Term id="benchmark">Benchmark</Term>
                  </TableHead>
                  <TableHead className="text-right">
                    <Term id="excess_return">vs B&amp;H</Term>
                  </TableHead>
                  <TableHead>
                    <Term id="equity_curve">Strategy vs B&amp;H</Term>
                  </TableHead>
                  <TableHead className="text-right">
                    <Term id="sharpe">Sharpe</Term>
                  </TableHead>
                  <TableHead className="text-right">
                    <Term id="max_drawdown">Max DD</Term>
                  </TableHead>
                  <TableHead className="text-right">
                    <Term id="trades">Trades</Term>
                  </TableHead>
                  <TableHead>
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    selected={selected.has(run.id)}
                    onToggle={() => toggle(run.id)}
                    onOpen={() => onOpen(run.id)}
                    onCancel={() => act(() => cancelRun(run.id))}
                    onRerun={() => rerun(run)}
                    onClone={() => onClone({ key: `${run.id}:${Date.now()}`, run })}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        </Panel>
      )}
    </div>
  );
}

function RunRow({
  run,
  selected,
  onToggle,
  onOpen,
  onCancel,
  onRerun,
  onClone,
}: {
  run: RunV2;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onCancel: () => void;
  onRerun: () => void;
  onClone: () => void;
}) {
  const name = runDisplayName(run);
  const metrics = run.metrics ?? null;
  const summary = run.summary ?? null;
  const active = isActiveRun(run);
  const preparing = awaitingResults(run);
  return (
    <TableRow data-testid={`run-row-${run.id}`} aria-selected={selected}>
      <TableCell>
        <input
          type="checkbox"
          aria-label={`Select ${name}`}
          checked={selected}
          onChange={onToggle}
        />
      </TableCell>
      <TableCell>
        <StatusBadge
          tone={STATUS_TONES[run.status]}
          testId="run-status"
          title={run.error ?? undefined}
        >
          {statusLabel(run)}
        </StatusBadge>
      </TableCell>
      <TableCell className="max-w-[16rem]">
        <button
          type="button"
          className="block max-w-full truncate text-left hover:text-primary"
          onClick={onOpen}
        >
          {name}
        </button>
        {preparing ? (
          <span
            className="block text-xs text-muted-foreground"
            data-testid="run-preparing"
            title="Recorded before results were stored with each run; the worker is computing them once."
          >
            preparing results…
          </span>
        ) : run.results_error ? (
          <span className="block truncate text-xs text-destructive" title={run.results_error}>
            Results unavailable · {run.results_error}
          </span>
        ) : null}
        {run.status === 'failed' ? (
          <span className="block truncate text-xs text-destructive" title={run.error ?? undefined}>
            {run.error_category ? `${FAILURE_LABELS[run.error_category]} · ` : ''}
            {run.error}
          </span>
        ) : null}
      </TableCell>
      <TableCell className="font-mono text-[11px]">{BAR_FREQUENCY_LABELS[barsOf(run)]}</TableCell>
      <TableCell className="max-w-[12rem] truncate text-xs" title={run.symbols.join(', ')}>
        <span className="tabular-nums">{run.symbols.length}</span> ·{' '}
        {run.symbols.slice(0, 3).join(' ')}
        {run.symbols.length > 3 ? '…' : ''}
      </TableCell>
      <TableCell className="whitespace-nowrap font-mono text-[11px] tabular-nums">
        {run.start_date} → {run.end_date}
      </TableCell>
      <TableCell className="whitespace-nowrap font-mono text-[11px] tabular-nums">
        {submittedAt(run.created_at)}
      </TableCell>
      <TableCell className="whitespace-nowrap font-mono text-[11px] tabular-nums">
        {durationCell(run)}
      </TableCell>
      <TableCell className="text-right">
        <Numeric value={metrics?.total_return ?? null} format="signedPercent" tone="signed" />
      </TableCell>
      <TableCell className="text-right">
        <Numeric value={summary?.benchmark_return ?? null} format="signedPercent" tone="muted" />
      </TableCell>
      <TableCell className="text-right">
        <Numeric value={summary?.excess_return ?? null} format="signedPercent" tone="signed" />
      </TableCell>
      <TableCell>
        {summary && summary.equity_spark && summary.equity_spark.length > 1 ? (
          <Sparkline
            strategy={summary.equity_spark}
            benchmark={summary.benchmark_spark ?? []}
            label={`${name}: strategy ends at ${summary.equity_spark[summary.equity_spark.length - 1].toFixed(2)}x, buy-and-hold at ${(summary.benchmark_spark?.[summary.benchmark_spark.length - 1] ?? 1).toFixed(2)}x`}
          />
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-right">
        <Numeric value={metrics?.sharpe_ratio ?? null} format="ratio" />
      </TableCell>
      <TableCell className="text-right">
        <Numeric value={metrics?.max_drawdown ?? null} format="percent" tone="signed" />
      </TableCell>
      <TableCell className="text-right">
        <Numeric value={metrics?.trade_count ?? null} format="integer" />
      </TableCell>
      <TableCell>
        <span className="flex items-center justify-end gap-1">
          {active ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`Cancel ${name}`}
              onClick={onCancel}
              disabled={run.cancel_requested}
            >
              <Ban size={16} strokeWidth={1.5} aria-hidden="true" />
            </Button>
          ) : (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`Re-run ${name}`}
              onClick={onRerun}
              disabled={!run.strategy}
            >
              <RotateCcw size={16} strokeWidth={1.5} aria-hidden="true" />
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-label={`Clone ${name} to the editor`}
            onClick={onClone}
            disabled={!run.strategy}
          >
            <Copy size={16} strokeWidth={1.5} aria-hidden="true" />
          </Button>
        </span>
      </TableCell>
    </TableRow>
  );
}

function RunDetail({
  runId,
  onBack,
  onClone,
  onOpen,
}: {
  runId: string;
  onBack: () => void;
  onClone: (clone: RunClone) => void;
  onOpen: (runId: string) => void;
}) {
  const { activeRun, select, cancelRun, submitStrategyRun, allRuns } = useRuns();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activeRun?.id !== runId) void select(runId);
  }, [runId, activeRun?.id, select]);

  // The list is refreshed while runs are active; a detail opened on a queued
  // run follows it there (RunsContext reloads the detail when it finishes).
  const listed = allRuns.find((run) => run.id === runId);
  const run: RunDetailV2 | null =
    activeRun?.id === runId ? ({ ...activeRun, ...(listed ?? {}) } as RunDetailV2) : null;

  if (!run) {
    return <EmptyState icon={Hourglass} title="Loading the run…" role="status" />;
  }
  const name = runDisplayName(run);
  const active = isActiveRun(run);
  // The list's shape: its strategy is the app's StrategySpec, which is what
  // re-running and cloning hand back to the builder.
  const record = (listed ?? run) as unknown as RunV2;

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="run-detail">
      <header className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2">
        <Button type="button" size="sm" variant="ghost" onClick={onBack}>
          <ArrowLeft size={16} strokeWidth={1.5} aria-hidden="true" />
          All runs
        </Button>
        <h2 className="min-w-0 flex-1 truncate font-mono text-sm">{name}</h2>
        <StatusBadge tone={STATUS_TONES[run.status]} testId="run-detail-status">
          {statusLabel(run)}
        </StatusBadge>
        {active ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={run.cancel_requested}
            onClick={() => cancelRun(run.id).catch((caught: Error) => setError(caught.message))}
          >
            <Ban size={16} strokeWidth={1.5} aria-hidden="true" />
            {run.cancel_requested ? 'Stopping…' : 'Cancel'}
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!run.strategy}
            onClick={async () => {
              if (!record.strategy) return;
              const next = await submitStrategyRun({
                strategy: record.strategy,
                symbols: record.symbols,
                start_date: record.start_date,
                end_date: record.end_date,
              });
              if (next) onOpen(next.id);
            }}
          >
            <RotateCcw size={16} strokeWidth={1.5} aria-hidden="true" />
            Re-run
          </Button>
        )}
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!run.strategy}
          onClick={() => onClone({ key: `${run.id}:${Date.now()}`, run: record })}
        >
          <Copy size={16} strokeWidth={1.5} aria-hidden="true" />
          Clone to editor
        </Button>
      </header>
      {error ? (
        <p role="alert" className="px-4 pt-2 text-xs text-destructive">
          {error}
        </p>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <GlossaryFrequency frequency={barsOf(record)}>
          <RunResultsView run={run} />
        </GlossaryFrequency>
      </div>
    </div>
  );
}
