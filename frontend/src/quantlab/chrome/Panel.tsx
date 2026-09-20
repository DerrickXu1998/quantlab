import type { ReactNode } from 'react';
import { CornerTicks } from '../../components/ui/corner-ticks';
import { StatusBadge } from '../../components/ui/status-badge';
import { cn } from '../../lib/utils';

export interface PanelProps {
  title: string;
  /** Right-aligned chrome in the panel header: chips, counts, small controls. */
  actions?: ReactNode;
  /** Non-null when the panel's numbers are invented; renders a SIMULATED tag. */
  simulated?: string;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}

/**
 * The one container on this surface. A 1px hairline and corner ticks, never a
 * shadow and never a radius above 4px — depth here comes from borders and
 * density, not from lifting things off the page.
 */
export function Panel({
  title,
  actions,
  simulated,
  className,
  bodyClassName,
  children,
}: PanelProps) {
  return (
    <section
      className={cn('relative border border-border bg-card', className)}
      aria-label={title}
    >
      <CornerTicks />
      <header className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          {title}
        </h2>
        <div className="flex items-center gap-2">
          {simulated ? (
            <StatusBadge tone="simulated" title={simulated} testId="simulated-tag">
              Simulated
            </StatusBadge>
          ) : null}
          {actions}
        </div>
      </header>
      <div className={cn('p-3', bodyClassName)}>{children}</div>
    </section>
  );
}
