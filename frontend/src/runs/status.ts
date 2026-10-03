import type { Run } from '../api/client';
import type { StatusTone } from '../components/ui/status-badge';
import { formatDuration, runTime } from '../strategies/barFrequency';

export type RunStatus = Run['status'];
export type FailureCategory = NonNullable<Run['error_category']>;

/** The label on a run's status chip. The words carry the meaning, never colour alone. */
export const STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export const STATUS_TONES: Record<RunStatus, StatusTone> = {
  queued: 'idle',
  running: 'active',
  completed: 'good',
  failed: 'bad',
  cancelled: 'disabled',
};

/** What kind of fix a failure needs, as a reader would say it. */
export const FAILURE_LABELS: Record<FailureCategory, string> = {
  data: 'Data',
  validation: 'Settings',
  limit: 'Too large',
  worker: 'Interrupted',
};

/** The chip text: "Queued #2", "Running", "Failed"... */
export function statusLabel(run: Pick<Run, 'status' | 'queue_position' | 'cancel_requested'>): string {
  if (run.status === 'queued' && run.queue_position) return `Queued #${run.queue_position}`;
  if (run.status === 'running' && run.cancel_requested) return 'Stopping';
  return STATUS_LABELS[run.status];
}


/**
 * "58 s" for a run of this size, or null when there is no estimate. The same
 * phase model Configure shows before submitting (barFrequency.runTime):
 * signals dominate, one pass per component.
 */
export function expectedDuration(
  bars: number | null | undefined,
  components = 1,
): string | null {
  if (!bars) return null;
  return formatDuration(runTime(bars, components).total);
}

export function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** Wall-clock time between two ISO stamps, or null when either is missing. */
export function durationBetween(start?: string | null, end?: string | null): string | null {
  if (!start || !end) return null;
  const ms = Date.parse(end) - Date.parse(start);
  if (!Number.isFinite(ms) || ms < 0) return null;
  return formatSeconds(Math.max(0, Math.round(ms / 1000)));
}

/** Components in a run's recorded strategy; 1 when it has none recorded. */
export function componentCount(run: { strategy?: { components?: unknown[] } | null }): number {
  return Math.max(1, run.strategy?.components?.length ?? 1);
}

/** One sentence on where a pending run is, for its results panel. */
export function pendingDetail(
  run: Pick<
    Run,
    'status' | 'queue_position' | 'estimated_bars' | 'started_at' | 'cancel_requested' | 'strategy'
  >,
): string {
  const expected = expectedDuration(run.estimated_bars, componentCount(run));
  if (run.status === 'queued') {
    const ahead =
      run.queue_position && run.queue_position > 1
        ? `${run.queue_position - 1} run${run.queue_position - 1 === 1 ? '' : 's'} ahead of it. `
        : 'It starts next. ';
    return `${ahead}${expected ? `Expected to take about ${expected} once it starts. ` : ''}You can leave this page; results appear in Strategies → Runs when it finishes.`;
  }
  if (run.cancel_requested) {
    return 'It stops at the next checkpoint and records nothing.';
  }
  return `${expected ? `Expected to take about ${expected}. ` : ''}You can leave this page; results appear here and in Strategies → Runs when it finishes.`;
}
