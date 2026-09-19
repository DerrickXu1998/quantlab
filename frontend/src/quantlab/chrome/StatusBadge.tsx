import { cn } from '../../lib/utils';

export type StatusTone = 'idle' | 'active' | 'good' | 'bad' | 'disabled';

const TONES: Record<StatusTone, string> = {
  idle: 'border-border text-muted-foreground',
  active: 'border-primary/50 bg-primary/10 text-primary',
  good: 'border-primary/50 text-primary',
  bad: 'border-destructive/50 bg-destructive/10 text-destructive',
  // A capability that does not exist. Visible, legible, and plainly off.
  disabled: 'border-border/60 text-muted-foreground/50',
};

export function StatusBadge({
  children,
  tone = 'idle',
  title,
  className,
}: {
  children: React.ReactNode;
  tone?: StatusTone;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        'rounded-sm border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
