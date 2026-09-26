import { cn } from '../../lib/utils';

export type StatusTone = 'idle' | 'active' | 'good' | 'bad' | 'disabled' | 'simulated';

const TONES: Record<StatusTone, string> = {
  idle: 'border-border text-muted-foreground',
  active: 'border-primary/50 bg-primary/10 text-primary',
  good: 'border-primary/50 text-primary',
  bad: 'border-destructive/50 bg-destructive/10 text-destructive',
  // A capability that does not exist. Visible, legible, and plainly off.
  disabled: 'border-border/60 text-muted-foreground/50',
  // Numbers standing in for data the backend does not have — said on the
  // element's face (and its title), never in a footnote.
  simulated: 'border-border text-muted-foreground',
};

export function StatusBadge({
  children,
  tone = 'idle',
  title,
  role,
  testId,
  className,
}: {
  children: React.ReactNode;
  tone?: StatusTone;
  title?: string;
  role?: string;
  testId?: string;
  className?: string;
}) {
  return (
    <span
      data-testid={testId}
      role={role}
      title={title}
      className={cn(
        'rounded-sm border px-1.5 py-px font-mono text-[11px] uppercase tracking-[0.12em]',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
