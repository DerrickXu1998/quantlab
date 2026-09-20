import { forwardRef, type HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';
import { CornerTicks } from './corner-ticks';

/**
 * Same grammar as the Quant Lab Panel: a 1px hairline and corner ticks, never
 * a shadow and never a radius above 4px — depth comes from borders and
 * density, not from lifting things off the page.
 */
export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('relative border border-border bg-card text-card-foreground', className)}
      {...props}
    >
      <CornerTicks />
      {children}
    </div>
  ),
);
Card.displayName = 'Card';

export const CardHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'flex items-center justify-between gap-3 border-b border-border px-3 py-2',
        className,
      )}
      {...props}
    />
  ),
);
CardHeader.displayName = 'CardHeader';

export const CardTitle = forwardRef<HTMLHeadingElement, HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h2
      ref={ref}
      className={cn(
        'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground',
        className,
      )}
      {...props}
    />
  ),
);
CardTitle.displayName = 'CardTitle';

export const CardContent = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-3', className)} {...props} />
  ),
);
CardContent.displayName = 'CardContent';
