import { Hourglass, SearchX, ServerCrash, type LucideIcon } from 'lucide-react';
import { cn } from '../../lib/utils';

/**
 * Designed absence. "Nothing here", "cannot reach it" and "it broke" are three
 * different answers and never share a treatment.
 */
export function EmptyState({
  icon: Icon,
  title,
  detail,
  tone = 'neutral',
  action,
  testId,
  role,
  className,
}: {
  icon: LucideIcon;
  title: string;
  detail?: string;
  tone?: 'neutral' | 'error';
  action?: React.ReactNode;
  testId?: string;
  /** Explicit ARIA role; an error tone implies `alert` when none is given. */
  role?: string;
  className?: string;
}) {
  const error = tone === 'error';
  return (
    <div
      data-testid={testId}
      role={role ?? (error ? 'alert' : undefined)}
      className={cn(
        'flex flex-col items-center justify-center gap-2 px-4 py-10 text-center',
        className,
      )}
    >
      <Icon
        strokeWidth={1.5}
        className={`h-5 w-5 ${error ? 'text-destructive' : 'text-muted-foreground'}`}
      />
      <p
        className={`font-mono text-[11px] uppercase tracking-[0.12em] ${
          error ? 'text-destructive' : 'text-muted-foreground'
        }`}
      >
        {title}
      </p>
      {detail ? <p className="max-w-xs text-xs text-muted-foreground">{detail}</p> : null}
      {action}
    </div>
  );
}

/*
  The Signal Viewer's three named states, ported onto EmptyState. `state` /
  `state-*` are stable identity hooks (tests and callers address these states
  by them); the Tailwind utilities alongside carry the styling.
*/

export function Loading() {
  return (
    <EmptyState
      icon={Hourglass}
      title="Loading signals…"
      role="status"
      className="state state-loading my-4"
    />
  );
}

export function EmptyResults() {
  return (
    <EmptyState
      icon={SearchX}
      title="No signals match the current filters."
      testId="empty-results"
      className="state state-empty my-4"
    />
  );
}

export function BackendUnavailable({ message }: { message?: string }) {
  return (
    <EmptyState
      icon={ServerCrash}
      tone="error"
      title="Backend unavailable"
      detail={`The signal service could not be reached${message ? `: ${message}` : '.'} Start the stack and reload this page.`}
      testId="backend-unavailable"
      className="state state-error my-4"
    />
  );
}
