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
  /**
   * Fill the height of the parent and let the body take the slack.
   *
   * The single most repeated fitting fault on this surface was a panel sitting
   * at its natural height inside a tall grid cell, leaving a band of empty
   * ground beneath it — 380px on Market, 290px on Replay. Every caller that
   * needed it was spelling out the same three flex classes in two places, or
   * forgetting `min-h-0` and getting a clipped table instead.
   *
   * `fill` makes the panel a flex column, gives the body `flex-1 min-h-0`, and
   * is the only thing a destination has to say.
   */
  fill?: boolean;
  /**
   * Scroll the body instead of letting it overflow.
   *
   * Only meaningful with `fill`, and the reason a long table now meets a
   * scroll edge rather than being sliced through a row.
   */
  scroll?: boolean;
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
  fill = false,
  scroll = false,
  className,
  bodyClassName,
  children,
}: PanelProps) {
  return (
    <section
      className={cn(
        'relative border border-border bg-card',
        fill && 'flex min-h-0 flex-1 flex-col',
        className,
      )}
      aria-label={title}
    >
      <CornerTicks />
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-3 py-2">
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
      <div
        className={cn(
          'p-3',
          fill && 'flex min-h-0 flex-1 flex-col',
          scroll && 'overflow-y-auto',
          bodyClassName,
        )}
      >
        {children}
      </div>
    </section>
  );
}
