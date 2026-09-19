import { useDataset } from '../api/DatasetProvider';

/**
 * What the numbers on screen actually are.
 *
 * Previously this was a fixed line asserting everything was "synthetic and
 * fictitious", which was false whenever a warehouse was configured — the badge
 * beside it said "Live history" at the same time. It now reads the same health
 * response the badge does, so the two cannot disagree.
 */
export function DataDisclaimer({ className = '' }: { className?: string }) {
  const state = useDataset();

  if (state.status === 'loading') return null;

  const text =
    state.status === 'unreachable'
      ? 'Data source unreachable — nothing shown here is current.'
      : state.health.dataset === 'warehouse'
        ? 'Prices and instruments are real ingested history. Bars are unadjusted for splits and dividends, and nothing here is investment advice.'
        : 'All instruments, prices, and signals shown here are synthetic and fictitious — demo data only, not real market data.';

  return (
    <p data-testid="data-disclaimer" className={className}>
      {text}
    </p>
  );
}
