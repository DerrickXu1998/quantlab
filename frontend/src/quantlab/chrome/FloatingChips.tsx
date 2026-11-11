import { cn } from '../../lib/utils';
import type { ReactNode } from 'react';

export function Chip({
  label,
  children,
  title,
  className,
}: {
  label: string;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        'flex items-center gap-1.5 rounded-sm border border-border bg-card px-2 py-0.5',
        className,
      )}
    >
      <span className="type-label text-muted-foreground">
        {label}
      </span>
      {children}
    </span>
  );
}
