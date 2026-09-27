import { StatusBadge } from './ui/status-badge';

export type DataSource = 'live' | 'demo' | 'simulated';

const LABELS: Record<DataSource, string> = {
  live: 'Live history',
  demo: 'Demo data',
  simulated: 'Simulated',
};

const TONES: Record<DataSource, 'good' | 'idle' | 'simulated'> = {
  live: 'good',
  demo: 'idle',
  simulated: 'simulated',
};

/**
 * A small, panel-level tag that says whether the numbers under it are real,
 * synthetic demo data, or simulated locally.
 *
 * Used inside `Panel` and anywhere else a dataset badge would be too large.
 */
export function DataSourceTag({
  source,
  title,
  testId,
  className,
}: {
  source: DataSource;
  title?: string;
  testId?: string;
  className?: string;
}) {
  return (
    <StatusBadge
      tone={TONES[source]}
      title={title ?? LABELS[source]}
      testId={testId}
      className={className}
    >
      {LABELS[source]}
    </StatusBadge>
  );
}
