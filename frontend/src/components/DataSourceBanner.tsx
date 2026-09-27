import { useDataset } from '../api/DatasetProvider';

/**
 * A thin global strip that appears when the active dataset is synthetic demo
 * data. It sits below the header so every screen sees it, without taking the
 * vertical space of a full banner.
 */
export function DataSourceBanner() {
  const state = useDataset();

  if (state.status === 'loading') return null;
  if (state.status === 'unreachable') {
    return (
      <div
        data-testid="data-source-banner"
        className="shrink-0 border-b border-destructive/30 bg-destructive/5 px-3 py-1 text-center text-xs text-destructive"
      >
        Data source unreachable — numbers shown here are not current.
      </div>
    );
  }
  if (state.health.dataset === 'warehouse') return null;

  return (
    <div
      data-testid="data-source-banner"
      className="shrink-0 border-b border-border bg-primary/5 px-3 py-1 text-center text-xs text-muted-foreground"
    >
      Demo data — all instruments, prices, and signals shown here are synthetic and fictitious.
    </div>
  );
}
