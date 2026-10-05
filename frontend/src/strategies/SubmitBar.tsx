import { CircleCheck, Play, ServerCrash, TriangleAlert } from 'lucide-react';
import type { RunV2 } from '../api/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/field';
import { StatusBadge } from '../components/ui/status-badge';
import { formatDuration, type RunSize } from './barFrequency';
import type { SECTION_IDS } from './StrategyBuilder';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

type Section = keyof typeof SECTION_IDS;

/**
 * The bar under Configure: name and save on the left, what is in the way and
 * Submit on the right. Always on screen, so the one action this tab exists for
 * is never a scroll away, and nothing that blocks it is either.
 *
 * Every problem is listed here *and* beside its field. Here each is a button
 * that takes you to the section it is about.
 */
export function SubmitBar({
  name,
  onNameChange,
  saved,
  dirty,
  saving,
  onSave,
  onSaveAsCopy,
  size,
  components,
  symbolsCount,
  blockers,
  hasErrors,
  warningCount,
  runError,
  submitting,
  canSubmit,
  onSubmit,
  queued,
  queuedFrom,
  onShowRun,
  onDismissQueued,
  onJump,
}: {
  name: string;
  onNameChange: (name: string) => void;
  saved: boolean;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onSaveAsCopy: () => void;
  size: RunSize;
  /** Signals are most of an intraday run's time, one pass per component. */
  components: number;
  symbolsCount: number;
  blockers: string[];
  hasErrors: boolean;
  warningCount: number;
  runError: string | null;
  submitting: boolean;
  canSubmit: boolean;
  onSubmit: () => void;
  queued: RunV2 | null;
  /** The start date that was submitted; the server may move it to where fundamentals begin. */
  queuedFrom: string | null;
  onShowRun: (runId: string) => void;
  onDismissQueued: () => void;
  onJump: (section: Section) => void;
}) {
  const issue = (section: Section, text: string, testId?: string) => (
    <li key={text} data-testid={testId}>
      <button
        type="button"
        className="text-left underline decoration-destructive/40 underline-offset-2 hover:decoration-destructive"
        onClick={() => onJump(section)}
      >
        {text}
      </button>
    </li>
  );

  return (
    <form
      aria-label="Submit backtest"
      data-testid="submit-bar"
      className="shrink-0 space-y-2 border-t border-border bg-card px-4 py-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[12rem] flex-1 space-y-1 sm:max-w-xs">
          <span className="flex items-center gap-2">
            <label className={MICRO} htmlFor="strategy-name">
              Name
            </label>
            {saved && !dirty ? (
              <StatusBadge tone="good" testId="draft-saved">
                Saved
              </StatusBadge>
            ) : dirty ? (
              <StatusBadge tone="idle" testId="draft-unsaved" title="Changes since the last save. Submitting does not need a save: the run records what is on screen.">
                Unsaved
              </StatusBadge>
            ) : null}
          </span>
          <Input
            id="strategy-name"
            value={name}
            placeholder="Name this strategy"
            onChange={(event) => onNameChange(event.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" variant="outline" disabled={saving} onClick={onSave}>
            {saving ? 'Saving…' : saved ? 'Save' : 'Save strategy'}
          </Button>
          {saved ? (
            <Button type="button" size="sm" variant="outline" disabled={saving} onClick={onSaveAsCopy}>
              Save as copy
            </Button>
          ) : null}
        </div>

        <span className="flex-1" />

        <div className="flex flex-wrap items-center justify-end gap-2">
          {symbolsCount > 0 ? (
            <p data-testid="strategy-run-size" className="font-mono text-xs text-muted-foreground">
              ≈ {size.bars.toLocaleString()} bars
              {size.time !== null
                ? ` · about ${formatDuration(size.time.total)} (read ${formatDuration(size.time.read)} · signals ${formatDuration(size.time.signals)} for ${Math.max(1, components)} component${components === 1 ? '' : 's'} · backtest ${formatDuration(size.time.backtest)})`
                : ''}
            </p>
          ) : null}
          {warningCount > 0 ? (
            <button
              type="button"
              data-testid="submit-warnings"
              title="Warnings do not stop a run. They say where its result may mislead."
              onClick={() => onJump('strategy')}
              className="inline-flex items-center gap-1 rounded-sm border border-border px-1.5 py-px font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground hover:text-foreground"
            >
              <TriangleAlert size={16} strokeWidth={1.5} aria-hidden="true" />
              {warningCount} warning{warningCount === 1 ? '' : 's'}
            </button>
          ) : null}
          <Button type="submit" className="px-4" disabled={!canSubmit}>
            <Play size={16} strokeWidth={1.5} aria-hidden="true" />
            {submitting ? 'Submitting…' : 'Submit backtest'}
          </Button>
        </div>
      </div>

      {blockers.length > 0 || hasErrors || size.blocker || symbolsCount === 0 ? (
        <ul role="alert" aria-label="What stops this run" className="space-y-1 text-xs text-destructive">
          {blockers.length > 0 ? (
            <li>
              <ul data-testid="strategy-blockers" className="space-y-1">
                {blockers.map((blocker) => issue('strategy', blocker))}
              </ul>
            </li>
          ) : null}
          {hasErrors
            ? issue(
                'strategy',
                'One or more component parameters is out of range. Fix the fields marked in Strategy before submitting.',
              )
            : null}
          {size.blocker ? issue('universe', size.blocker, 'strategy-size-blocker') : null}
          {symbolsCount === 0 ? issue('universe', 'Add at least one ticker to the universe.', 'strategy-no-symbols') : null}
        </ul>
      ) : null}

      {runError ? (
        <p
          role="alert"
          data-testid="builder-run-error"
          className="flex gap-2 border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-xs text-destructive"
        >
          <ServerCrash size={16} strokeWidth={1.5} aria-hidden="true" className="mt-px shrink-0" />
          <span>Backtest could not be submitted: {runError}</span>
        </p>
      ) : null}

      {queued ? (
        <div
          role="status"
          data-testid="run-queued"
          className="flex flex-wrap items-center gap-2 border border-primary/40 bg-primary/5 px-2 py-1.5 text-xs"
        >
          <CircleCheck size={16} strokeWidth={1.5} aria-hidden="true" className="shrink-0 text-primary" />
          <span className="min-w-0 flex-1">
            Queued "{queued.name ?? queued.strategy?.name ?? queued.model_name}"
            {queued.queue_position ? ` — #${queued.queue_position} in line` : ''}. It runs in the
            background; you can keep editing and submit another.
            {queuedFrom && queued.start_date > queuedFrom ? (
              <span data-testid="run-queued-start-moved">
                {' '}
                It starts {queued.start_date}, not {queuedFrom}: the fundamentals it reads begin
                then.
              </span>
            ) : null}
          </span>
          <Button type="button" size="sm" variant="outline" onClick={() => onShowRun(queued.id)}>
            View in Runs
          </Button>
          <Button type="button" size="sm" variant="ghost" aria-label="Dismiss" onClick={onDismissQueued}>
            Dismiss
          </Button>
        </div>
      ) : null}
    </form>
  );
}
