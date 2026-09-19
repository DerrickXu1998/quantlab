import { PackageOpen } from 'lucide-react';
import { EmptyState } from '../chrome/EmptyState';
import { Numeric } from '../chrome/Numeric';
import { StatusBadge } from '../chrome/StatusBadge';
import type { Strategy } from '../data/useStrategies';

const NO_EXECUTION = 'No execution backend — QuantLab computes signals, it does not place orders.';

/**
 * Registered models, with their run history.
 *
 * The LIVE/PAPER/BACKTEST chips a terminal usually carries are not faked here.
 * BACKTEST is the only mode that exists, so it is the only one lit; the other
 * two are rendered visibly disabled with the reason on hover. Showing a green
 * LIVE badge over a system that cannot trade would be the single most
 * misleading thing on the screen.
 */
export function StrategyList({
  strategies,
  selected,
  onSelect,
}: {
  strategies: Strategy[];
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  if (strategies.length === 0) {
    return (
      <EmptyState
        testId="strategies-empty"
        icon={PackageOpen}
        title="No strategies registered"
        detail="The model registry is empty. Register a signal rule in the backend and it appears here without a frontend change."
      />
    );
  }

  return (
    <ul data-testid="strategy-list" className="divide-y divide-border">
      {strategies.map(({ model, runs, latest }) => {
        const active = model.name === selected;
        return (
          <li key={`${model.name}@${model.version}`}>
            <button
              type="button"
              onClick={() => onSelect(model.name)}
              aria-current={active ? 'true' : undefined}
              className={`w-full border-l-2 px-3 py-2.5 text-left transition-colors ${
                active ? 'border-l-primary bg-primary/5' : 'border-l-transparent hover:bg-accent/40'
              }`}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="truncate font-mono text-[12px]">{model.name}</span>
                <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                  v{model.version}
                </span>
              </span>

              <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <StatusBadge tone="active">Backtest</StatusBadge>
                <StatusBadge tone="disabled" title={NO_EXECUTION}>
                  Paper
                </StatusBadge>
                <StatusBadge tone="disabled" title={NO_EXECUTION}>
                  Live
                </StatusBadge>
              </span>

              <span className="mt-1.5 flex flex-wrap items-center gap-x-3 text-[10px] text-muted-foreground">
                <span className="font-mono">{model.lookback_days}d lookback</span>
                <span className="font-mono">{model.scale_class.replace('_', '-')}</span>
                <span className="font-mono">
                  {runs.length} {runs.length === 1 ? 'run' : 'runs'}
                </span>
                {latest ? (
                  <span className="flex items-center gap-1">
                    last
                    <Numeric value={latest.signal_count} format="integer" className="text-[10px]" />
                    sig
                  </span>
                ) : null}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
