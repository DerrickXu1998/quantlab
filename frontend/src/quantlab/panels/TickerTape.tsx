import { Numeric } from '../chrome/Numeric';
import { useFeedSymbols, useTick } from '../feed/FeedProvider';

function Item({ symbol }: { symbol: string }) {
  const tick = useTick(symbol);
  return (
    <span className="flex items-center gap-2 whitespace-nowrap px-4">
      <span className="font-mono text-[11px] text-muted-foreground">{symbol}</span>
      <Numeric value={tick?.price} format="price" className="text-[11px]" />
      <Numeric
        value={tick?.changePct}
        format="signedPercent"
        tone="signed"
        className="text-[10px]"
      />
    </span>
  );
}

/**
 * The strip across the bottom. It scrolls nothing and blinks nothing: the
 * values simply update in place, because a moving marquee would be a second
 * continuous animation and the budget is one.
 */
export function TickerTape() {
  const symbols = useFeedSymbols();
  if (symbols.length === 0) return null;

  return (
    <div
      data-testid="ticker-tape"
      className="flex items-center overflow-x-auto border-t border-border bg-card py-1.5"
    >
      {symbols.map((symbol) => (
        <Item key={symbol} symbol={symbol} />
      ))}
    </div>
  );
}
