import { PackageOpen } from 'lucide-react';
import type { ModelEntry } from '../runs/RunsContext';
import { EmptyState } from './ui/empty-state';
import { Numeric } from './ui/numeric';
import { LifecycleRow } from './ui/lifecycle';


/**
 * The model list, used by both Research and Strategies.
 *
 * A model is not a strategy until it is deployed, so the list says "models".
 * Every entry comes from the backend registry at request time — nothing about
 * model identity is hardcoded here, which is what makes registering a model
 * enough to make it appear (Constitution II).
 *
 * The LIVE/PAPER/BACKTEST chips a terminal usually carries are not faked here.
 * BACKTEST is the only mode the backend has, so it is the only one lit; the
 * other two are rendered visibly disabled with the reason on hover. Showing a
 * lit LIVE badge over a system that cannot trade would be the single most
 * misleading thing on the screen.
 */
export function ModelList({
  entries,
  selected,
  onSelect,
}: {
  entries: ModelEntry[];
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  if (entries.length === 0) {
    return (
      <EmptyState
        testId="model-list-empty"
        icon={PackageOpen}
        title="No models registered"
        detail="The model registry is empty. Register a signal rule in the backend and it appears here without a frontend change."
      />
    );
  }

  return (
    <ul data-testid="model-list" className="divide-y divide-border">
      {entries.map(({ model, runs, latest }) => {
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
                <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                  v{model.version}
                </span>
              </span>

              <span className="mt-1 block text-xs text-muted-foreground">
                {model.direction_semantics}
              </span>

              <span className="mt-1.5 block">
                <LifecycleRow />
              </span>

              <span className="mt-1.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                <span className="font-mono">
                  <Numeric value={model.lookback_days} format="integer" className="text-xs" />
                  d lookback
                </span>
                <span className="font-mono">{model.scale_class.replace('_', '-')}</span>
                <span className="font-mono">
                  <Numeric value={runs.length} format="integer" className="text-xs" />{' '}
                  {runs.length === 1 ? 'run' : 'runs'}
                </span>
                {latest ? (
                  <span className="flex items-center gap-1">
                    last
                    <Numeric value={latest.signal_count} format="integer" className="text-xs" />
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
