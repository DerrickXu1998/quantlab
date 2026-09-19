import { useDataset } from '../api/DatasetProvider';

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
    return <span className="text-[11px] text-muted-foreground">checking data source…</span>;
  }

  // "Cannot reach the data" and "no data" are different answers and must not
  // look the same.
  if (state.status === 'unreachable') {
    return (
      <span
        role="alert"
        data-testid="dataset-badge"
        className="rounded-md border border-destructive/40 bg-destructive/10 px-2 py-0.5 text-[11px] font-semibold text-destructive"
      >
        Data source unreachable
      </span>
    );
  }

  const warehouse = state.health.dataset === 'warehouse';
  return (
    <span
      data-testid="dataset-badge"
      title={
        warehouse
          ? 'Real ingested history'
          : 'Synthetic demo data — fictitious instruments and prices'
      }
      className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
        warehouse
          ? 'border-success/40 bg-success/10 text-success'
          : 'border-border bg-muted text-muted-foreground'
      }`}
    >
      {warehouse ? 'Live history' : 'Demo data'}
    </span>
  );
}
