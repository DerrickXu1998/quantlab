import type { CSSProperties, ReactNode } from 'react';

/** The brief's one high-impact moment: 80ms between panels, once, on entry. */
export const CASCADE_STEP_MS = 80;

/**
 * Staggers its children in on mount.
 *
 * Delay comes from the index rather than from a timer, so there is no state,
 * no re-render, and nothing to clean up. `data-cascade` is the hook the
 * reduced-motion rule in styles.css uses to switch the whole thing off.
 */
export function CascadeItem({
  index,
  children,
  className,
  style,
}: {
  index: number;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      data-cascade=""
      className={`animate-panel-in ${className ?? ''}`}
      style={{ animationDelay: `${index * CASCADE_STEP_MS}ms`, ...style }}
    >
      {children}
    </div>
  );
}
