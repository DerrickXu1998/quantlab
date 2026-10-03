import { CircleCheck, TriangleAlert, X } from 'lucide-react';
import { useEffect } from 'react';
import { navigate } from '../chrome/router';
import { cn } from '../lib/utils';
import { useOptionalRuns, type RunNotice } from './RunsContext';

/** How long a success stays up. Failures stay until dismissed. */
const SUCCESS_MS = 8000;

/**
 * Toasts for backtests that finished while you were elsewhere in the app.
 *
 * Runs execute in the background, so the moment one finishes is usually not a
 * moment anyone is watching its page. A success fades after a few seconds; a
 * failure stays until dismissed, because a quietly vanishing failure is one
 * nobody saw.
 */
export function RunNotices() {
  const runs = useOptionalRuns();
  if (!runs || runs.notices.length === 0) return null;
  return (
    <div
      aria-label="Backtest notifications"
      className="pointer-events-none fixed bottom-16 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      data-testid="run-notices"
    >
      {runs.notices.map((notice) => (
        <Toast key={notice.id} notice={notice} onDismiss={() => runs.dismissNotice(notice.id)} />
      ))}
    </div>
  );
}

function Toast({ notice, onDismiss }: { notice: RunNotice; onDismiss: () => void }) {
  useEffect(() => {
    if (notice.tone === 'bad') return undefined;
    const timer = window.setTimeout(onDismiss, SUCCESS_MS);
    return () => window.clearTimeout(timer);
  }, [notice, onDismiss]);

  const Icon = notice.tone === 'bad' ? TriangleAlert : CircleCheck;
  return (
    <div
      role={notice.tone === 'bad' ? 'alert' : 'status'}
      className={cn(
        'pointer-events-auto flex items-start gap-2 border bg-card px-3 py-2 text-xs animate-panel-in',
        notice.tone === 'bad' ? 'border-destructive/50 text-destructive' : 'border-primary/50',
      )}
    >
      <Icon
        size={16}
        strokeWidth={1.5}
        aria-hidden="true"
        className={cn('mt-px shrink-0', notice.tone === 'bad' ? '' : 'text-primary')}
      />
      <p className="min-w-0 flex-1">{notice.text}</p>
      <button
        type="button"
        className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground hover:text-foreground"
        onClick={() => {
          navigate('strategies', { tab: 'runs', run: notice.runId });
          onDismiss();
        }}
      >
        Open
      </button>
      <button type="button" aria-label="Dismiss" className="text-muted-foreground hover:text-foreground" onClick={onDismiss}>
        <X size={16} strokeWidth={1.5} aria-hidden="true" />
      </button>
    </div>
  );
}
