import type { CatalogModel } from '../api/types';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

/**
 * The other instruments a rule reads — the macro gate's VIX and HY spread.
 *
 * Said on the card because it is a data dependency the user cannot see from
 * the parameters: without VIX.FRED in the store the gate never opens, and the
 * run is refused rather than silently never trading.
 */
export function RequiresSeries({ model, testId }: { model: CatalogModel; testId?: string }) {
  if (model.requires_series.length === 0) return null;
  return (
    <div data-testid={testId} className="space-y-0.5">
      <p className={MICRO}>Reads market series</p>
      <p className="font-mono text-xs">{model.requires_series.join(' · ')}</p>
    </div>
  );
}
