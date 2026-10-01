import { History, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { Run } from '../api/client';
import { runDisplayName } from '../runs/labels';
import { useRuns } from '../runs/RunsContext';
import { Button } from './ui/button';
import { EmptyState } from './ui/empty-state';
import { Numeric } from './ui/numeric';
import { StatusBadge } from './ui/status-badge';

function RunRow({
  run,
  selected,
  checked,
  onSelect,
  onToggle,
}: {
  run: Run;
  selected: boolean;
  checked: boolean;
  onSelect: () => void;
  onToggle: () => void;
}) {
  return (
    <li className="group relative flex items-start gap-1 pl-2">
      <input
        type="checkbox"
        data-testid={`select-run-${run.id}`}
        aria-label={`Select run ${runDisplayName(run)}`}
        checked={checked}
        onChange={onToggle}
        className="mt-3 shrink-0 accent-primary"
      />
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? 'true' : undefined}
        className={`w-full border-l-2 px-3 py-2 text-left transition-colors ${
          selected ? 'border-l-primary bg-primary/5' : 'border-l-transparent hover:bg-accent/40'
        }`}
      >
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate font-mono text-[11px]">{runDisplayName(run)}</span>
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
    </li>
  );
}

/**
 * Every recorded run, newest first, with a saved-only filter — saving a run is
 * what marks it worth keeping, so saved is the default view.
 *
 * Cleanup is bulk, not per-row: tick the runs to discard, then the single
 * delete icon in the toolbar. Because there is no undo against the backend,
 * the confirmation is a modal that names every run about to be deleted, not
 * an inline popover that is easy to click through.
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
  const { remove } = useRuns();
  const [savedOnly, setSavedOnly] = useState(true);
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const visible = useMemo(
    () => (savedOnly ? runs.filter((run) => run.name) : runs),
    [runs, savedOnly],
  );

  const toggle = (runId: string) =>
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });

  const checkedVisible = visible.filter((run) => checked.has(run.id));
  const allChecked = visible.length > 0 && checkedVisible.length === visible.length;
  const toggleAll = () =>
    setChecked(allChecked ? new Set() : new Set(visible.map((run) => run.id)));

  // The dialog names what it deletes, so it lists every checked run, including
  // ones the current filter has hidden from the rail.
  const checkedRuns = runs.filter((run) => checked.has(run.id));

  useEffect(() => {
    if (!confirming) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !deleting) setConfirming(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [confirming, deleting]);

  const confirmRemove = async () => {
    setDeleting(true);
    try {
      for (const runId of checked) {
        await remove(runId);
      }
      setChecked(new Set());
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  };

  return (
    <div data-testid="runs-rail">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <input
          type="checkbox"
          data-testid="select-all-runs"
          aria-label="Select all listed runs"
          checked={allChecked}
          onChange={toggleAll}
          disabled={visible.length === 0}
          className="shrink-0 accent-primary"
        />
        <div
          role="group"
          aria-label="Run filter"
          className="grid grid-cols-2 gap-px rounded-sm border border-border bg-border"
        >
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
        <span className="flex-1" />
        {checked.size > 0 ? (
          <span
            data-testid="runs-selected-count"
            className="font-mono text-[11px] text-muted-foreground"
          >
            {checked.size} selected
          </span>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-label="Delete selected runs"
          title={checked.size > 1 ? `Delete ${checked.size} runs` : 'Delete run'}
          disabled={checked.size === 0}
          onClick={() => setConfirming(true)}
        >
          <Trash2 size={16} strokeWidth={1.5} aria-hidden="true" />
        </Button>
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
              checked={checked.has(run.id)}
              onSelect={() => onSelect(run.id)}
              onToggle={() => toggle(run.id)}
            />
          ))}
        </ul>
      )}

      {confirming ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/70"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !deleting) setConfirming(false);
          }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label="Delete selected runs"
            data-testid="bulk-delete-dialog"
            className="flex max-h-[70vh] w-[22rem] flex-col rounded-sm border border-border bg-card p-4"
          >
            <h2 className="text-sm font-medium">
              Delete {checkedRuns.length} {checkedRuns.length === 1 ? 'run' : 'runs'}?
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              This removes the runs and their stored signals. There is no undo.
            </p>
            <ul className="mt-3 min-h-0 flex-1 divide-y divide-border overflow-y-auto rounded-sm border border-border">
              {checkedRuns.map((run) => (
                <li key={run.id} className="px-3 py-1.5 font-mono text-[11px]">
                  {runDisplayName(run)}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={deleting}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={deleting}
                className="border-destructive/50 text-destructive hover:text-destructive"
                onClick={() => void confirmRemove()}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
