import type { ReactNode } from 'react';

/**
 * A chip row that sits across a panel's top edge rather than inside it.
 *
 * The overlap is the point: it breaks the grid just enough that the surface
 * reads as instrumentation layered over a workspace instead of a column of
 * cards. Kept to one element per screen — repeated, it stops being a deliberate
 * break and becomes noise.
 */
export function FloatingChips({ children }: { children: ReactNode }) {
  return (
    <div className="pointer-events-none absolute -top-3 left-4 z-10 flex flex-wrap items-center gap-1.5">
      {children}
    </div>
  );
}

export function Chip({
  label,
  children,
  title,
}: {
  label: string;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className="pointer-events-auto flex items-center gap-1.5 rounded-sm border border-border bg-card px-2 py-1"
    >
      <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      {children}
    </span>
  );
}
