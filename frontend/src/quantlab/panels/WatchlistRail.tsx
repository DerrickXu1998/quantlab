import { WifiOff } from 'lucide-react';
import type { Instrument } from '../../api/client';
import { Sparkline } from '../charts/Sparkline';
import { EmptyState } from '../chrome/EmptyState';
import { FlashNumber } from '../chrome/FlashNumber';
import { Numeric } from '../chrome/Numeric';
import { useTick } from '../feed/FeedProvider';

/**
 * One instrument, on two lines.
 *
 * On one line the rail had to fit symbol, name, sparkline, price and change
 * across 240px, and the name — the only part that is not a number — lost every
 * time: "Xanthic Blend Partn…" at nineteen characters. Two lines give the
 * identifiers the top row and the movement the bottom one, which leaves the
 * name roughly 165px instead of 95px and lets every instrument here read in
 * full. `title` carries the untruncated string for the few that still clip.
 */
function Row({
  instrument,
  selected,
  onSelect,
}: {
  instrument: Instrument;
  selected: boolean;
  onSelect: () => void;
}) {
  const tick = useTick(instrument.symbol);
  const rising = (tick?.changePct ?? 0) >= 0;

  return (
    <button
      type="button"
      onClick={onSelect}
      title={instrument.name}
      aria-current={selected ? 'true' : undefined}
      className={`flex w-full flex-col gap-1 border-l-2 px-3 py-2 text-left transition-colors ${
        selected ? 'border-l-primary bg-primary/5' : 'border-l-transparent hover:bg-accent/40'
      }`}
    >
      <span className="flex w-full items-center justify-between gap-2">
        <span className="truncate font-mono text-[11px] tracking-[0.12em]">
          {instrument.symbol}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <Sparkline values={tick?.history ?? []} rising={rising} />
          <FlashNumber value={tick?.price} format="price" className="text-[11px]" />
        </span>
      </span>
      <span className="flex w-full items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-[10px] text-muted-foreground">
          {instrument.name}
        </span>
        <Numeric
          value={tick?.changePct}
          format="signedPercent"
          tone="signed"
          className="shrink-0 text-[10px]"
        />
      </span>
    </button>
  );
}

/**
 * The 240px left rail. Real instruments at real last closes; the movement on
 * top of them is the simulated feed.
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

  return (
    <div className="divide-y divide-border">
      {instruments.map((instrument) => (
        <Row
          key={instrument.symbol}
          instrument={instrument}
          selected={instrument.symbol === selected}
          onSelect={() => onSelect(instrument.symbol)}
        />
      ))}
    </div>
  );
}
