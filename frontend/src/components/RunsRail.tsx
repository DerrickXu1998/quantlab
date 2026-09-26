import { History, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { Run } from '../api/client';
import { useRuns } from '../runs/RunsContext';
import { Button } from './ui/button';
import { EmptyState } from './ui/empty-state';
import { Numeric } from './ui/numeric';
import { StatusBadge } from './ui/status-badge';

function RunRow({
  run,
  selected,
  onSelect,
}: {
  run: Run;
  selected: boolean;
  onSelect: () => void;
}) {
  const { remove } = useRuns();
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  return (
    <li className="group relative">
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? 'true' : undefined}
        className={`w-full border-l-2 px-3 py-2 text-left transition-colors ${
          selected ? 'border-l-primary bg-primary/5' : 'border-l-transparent hover:bg-accent/40'
        }`}
      >
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate font-mono text-[11px]">
            {run.name ?? run.model_name}
          </span>
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
            {run.created_at.slice(0, 10)}
          </span>
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span className="font-mono">v{run.model_version}</span>
          <span className="flex items-center gap-1 font-mono">
            <Numeric value={run.signal_count} format="integer" className="text-xs" />
            sig
          </span>
          <StatusBadge tone={run.dataset === 'warehouse' ? 'good' : 'idle'}>
            {run.dataset === 'warehouse' ? 'Live' : 'Demo'}
          </StatusBadge>
          {run.status === 'failed' ? <StatusBadge tone="bad">Failed</StatusBadge> : null}
          {run.re_runnable === false ? (
            <StatusBadge tone="bad" title="Recorded against a dataset that is not the active one.">
              Not reproducible
            </StatusBadge>
          ) : null}
          {run.model_available === false ? (
            <StatusBadge tone="bad" title="The recorded model/version is no longer registered.">
              Model gone
            </StatusBadge>
          ) : null}
        </span>
      </button>

      <span className="absolute right-2 top-2">
        {confirming ? (
          <span className="flex items-center gap-1">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={deleting}
              className="border-destructive/50 text-destructive hover:text-destructive"
              onClick={async () => {
                setDeleting(true);
                try {
                  await remove(run.id);
                } finally {
                  setDeleting(false);
                  setConfirming(false);
                }
              }}
            >
              {deleting ? 'Deleting…' : 'Confirm'}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Keep
            </Button>
          </span>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-label={`Delete run ${run.name ?? run.id}`}
            title="Delete this run"
            onClick={() => setConfirming(true)}
          >
            <Trash2 size={16} strokeWidth={1.5} aria-hidden="true" />
          </Button>
        )}
      </span>
    </li>
  );
}

/**
 * Every recorded run, newest first, with a saved-only filter — saving a run is
 * what marks it worth keeping, so saved is the default view.
 *
 * Delete is a two-step row action: the first click arms it, the second
 * confirms. There is no undo against the backend.
 */
export function RunsRail({
  runs,
  selectedId,
  onSelect,
}: {
  runs: Run[];
  selectedId: string | null;
  onSelect: (runId: string) => void;
}) {
  const [savedOnly, setSavedOnly] = useState(true);
  const visible = useMemo(
    () => (savedOnly ? runs.filter((run) => run.name) : runs),
    [runs, savedOnly],
  );

  return (
    <div data-testid="runs-rail">
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        <div role="group" aria-label="Run filter" className="grid grid-cols-2 gap-px rounded-sm border border-border bg-border">
          {(['saved', 'all'] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={(option === 'saved') === savedOnly}
              onClick={() => setSavedOnly(option === 'saved')}
              className={`px-2 py-1 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors ${
                (option === 'saved') === savedOnly
                  ? 'bg-primary/10 text-primary'
                  : 'bg-card text-muted-foreground hover:text-foreground'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <EmptyState
          testId="runs-rail-empty"
          icon={History}
          title={savedOnly ? 'No saved experiments' : 'No runs yet'}
          detail={
            savedOnly
              ? 'Run and save an experiment to pin it here.'
              : 'Run a backtest in Strategies or Research and it appears here.'
          }
        />
      ) : (
        <ul className="divide-y divide-border">
          {visible.map((run) => (
            <RunRow
              key={run.id}
              run={run}
              selected={run.id === selectedId}
              onSelect={() => onSelect(run.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
