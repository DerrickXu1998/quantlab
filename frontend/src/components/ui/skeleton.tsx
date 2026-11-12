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

const ROW_WIDTHS = ['w-3/4', 'w-1/2', 'w-2/3', 'w-5/6', 'w-1/2', 'w-3/5'];

/**
 * A loading state in the outline of what is coming. The label is read by
 * screen readers (and tests) and never shown: the shape says "loading".
 *
 * `rows` is a list or table, `chart` is a plot with its axis, `detail` is a
 * page of headline figures above a chart.
 */
export function SkeletonState({
  label,
  shape = 'rows',
  rows = 6,
  testId,
  className,
}: {
  label: string;
  shape?: 'rows' | 'chart' | 'detail';
  rows?: number;
  testId?: string;
  className?: string;
}) {
  return (
    <div role="status" data-testid={testId} className={cn('p-4', className)}>
      <span className="sr-only">{label}</span>
      {shape === 'detail' ? (
        <div className="mb-6 flex flex-wrap gap-8">
          {[0, 1, 2, 3].map((index) => (
            <div key={index}>
              <Skeleton className="h-3 w-20" />
              <Skeleton className="mt-2 h-6 w-24" />
            </div>
          ))}
        </div>
      ) : null}
      {shape === 'rows' ? (
        <div className="space-y-4">
          {Array.from({ length: rows }, (_, index) => (
            <div key={index} className="space-y-2">
              <Skeleton className={cn('h-3', ROW_WIDTHS[index % ROW_WIDTHS.length])} />
              <Skeleton className="h-3 w-1/3" />
            </div>
          ))}
        </div>
      ) : (
        <Skeleton className="h-64 w-full" />
      )}
    </div>
  );
}
