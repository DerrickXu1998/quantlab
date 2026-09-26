import { useDataset } from '../api/DatasetProvider';
import { StatusBadge } from '../components/ui/status-badge';

/**
 * Which dataset is answering, shown without opening a menu.
 *
 * Read from the health response, never inferred from the shape of the data —
 * the front end does not decide which store is active, and guessing would make
 * a synthetic result mistakable for a real one.
 */
export function DatasetBadge() {
  const state = useDataset();

  if (state.status === 'loading') {
    return <span className="text-xs text-muted-foreground">checking data source…</span>;
  }

  // "Cannot reach the data" and "no data" are different answers and must not
  // look the same.
  if (state.status === 'unreachable') {
    return (
      <StatusBadge tone="bad" role="alert" testId="dataset-badge">
        Data source unreachable
      </StatusBadge>
    );
  }

  const warehouse = state.health.dataset === 'warehouse';
  return (
    <StatusBadge
      tone={warehouse ? 'good' : 'idle'}
      testId="dataset-badge"
      title={
        warehouse
          ? 'Real ingested history'
          : 'Synthetic demo data — fictitious instruments and prices'
      }
    >
      {warehouse ? 'Live history' : 'Demo data'}
    </StatusBadge>
  );
}
