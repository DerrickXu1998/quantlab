import { cn } from '../../lib/utils';

/**
 * A still placeholder in the shape of what is loading.
 *
 * Deliberately not animated: the surface allows one entrance and nothing that
 * moves at rest, and a shimmer on every load would be a third. The block holds
 * the layout so the page does not jump when the data lands.
 */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn('rounded-sm bg-muted', className)} />;
}
