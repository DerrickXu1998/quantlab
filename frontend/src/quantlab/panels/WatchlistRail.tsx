import { WifiOff } from 'lucide-react';
import type { Instrument } from '../../api/client';
import { Sparkline } from '../charts/Sparkline';
import { EmptyState } from '../chrome/EmptyState';
import { FlashNumber } from '../chrome/FlashNumber';
import { Numeric } from '../chrome/Numeric';
import { StatusBadge } from '../chrome/StatusBadge';
import { useTick } from '../feed/FeedProvider';

const NO_MACRO_TICKS =
  'A daily value series, not a price — macro instruments are excluded from the simulated tick feed.';

function Row({
  instrument,
  selected,
  onSelect,
}: {
  instrument: Instrument;
  selected: boolean;
  onSelect: () => void;
}) {
  // Macro symbols carry no seed, so this subscription simply never fires.
  const tick = useTick(instrument.symbol);
  const rising = (tick?.changePct ?? 0) >= 0;
  const isMacro = instrument.kind === 'macro';

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
      className={`flex w-full items-center justify-between gap-2 border-l-2 px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-primary ${
        selected
          ? 'border-l-primary bg-primary/5'
          : 'border-l-transparent hover:bg-accent/40'
      }`}
    >
      <span className="min-w-0">
        <span className="block truncate font-mono text-[11px] tracking-[0.12em]">
          {instrument.symbol}
        </span>
        {/* The name is the macro series' identity: "10-Year Treasury constant
            maturity yield" says what UST10Y.FRED never could. */}
        <span className={isMacro ? 'block text-[10px] text-muted-foreground' : 'block truncate text-[10px] text-muted-foreground'}>
          {instrument.name}
        </span>
      </span>
      {isMacro ? (
        <StatusBadge tone="idle" title={NO_MACRO_TICKS}>
          Macro
        </StatusBadge>
      ) : (
        <span className="flex shrink-0 items-center gap-2">
          <Sparkline values={tick?.history ?? []} rising={rising} />
          <span className="flex flex-col items-end">
            <FlashNumber value={tick?.price} format="price" className="text-[11px]" />
            <Numeric
              value={tick?.changePct}
              format="signedPercent"
              tone="signed"
              className="text-[10px]"
            />
          </span>
        </span>
      )}
    </button>
  );
}

interface Group {
  id: 'equity' | 'macro';
  label: string;
  items: Instrument[];
}

/**
 * The 240px left rail, grouped by instrument kind. Equities carry the
 * simulated feed's live columns; macro series are daily values and get no
 * sparkline, because inventing per-second ticks for a yield would be a lie.
 */
export function WatchlistRail({
  instruments,
  selected,
  onSelect,
  error,
}: {
  instruments: Instrument[];
  selected: string | null;
  onSelect: (symbol: string) => void;
  error: string | null;
}) {
  if (error) {
    return (
      <EmptyState
        testId="watchlist-disconnected"
        icon={WifiOff}
        tone="error"
        title="Feed disconnected"
        detail={error}
      />
    );
  }

  const groups: Group[] = (
    [
      { id: 'equity', label: 'Equities', items: [] },
      { id: 'macro', label: 'Macro series', items: [] },
    ] as Group[]
  )
    .map((group) => ({
      ...group,
      items: instruments.filter((instrument) =>
        group.id === 'macro' ? instrument.kind === 'macro' : instrument.kind !== 'macro',
      ),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <div data-testid="watchlist-rail">
      {groups.map((group) => (
        <div key={group.id} data-testid={`watchlist-group-${group.id}`}>
          <h3 className="border-b border-border px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            {group.label}
            <span className="ml-2 text-muted-foreground/60">{group.items.length}</span>
          </h3>
          <div className="divide-y divide-border">
            {group.items.map((instrument) => (
              <Row
                key={instrument.symbol}
                instrument={instrument}
                selected={instrument.symbol === selected}
                onSelect={() => onSelect(instrument.symbol)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
