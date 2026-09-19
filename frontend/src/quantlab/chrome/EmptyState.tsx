import type { LucideIcon } from 'lucide-react';

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
}: {
  icon: LucideIcon;
  title: string;
  detail?: string;
  tone?: 'neutral' | 'error';
  action?: React.ReactNode;
  testId?: string;
}) {
  const error = tone === 'error';
  return (
    <div
      data-testid={testId}
      role={error ? 'alert' : undefined}
      className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center"
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
