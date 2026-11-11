import { displaySymbol } from '../../research/format';
import { Numeric } from '../chrome/Numeric';
import type { Quote } from '../data/useWatchlist';

/**
 * The watchlist's last stored closes along the bottom of the shell. Real
 * end-of-day prices: each item carries the date of its bar on hover, and
 * nothing ticks.
 */
export function TickerTape({ quotes }: { quotes: Record<string, Quote> }) {
  const symbols = Object.keys(quotes);
  if (symbols.length === 0) return null;

  return (
    <div
      data-testid="ticker-tape"
      className="flex items-center overflow-x-auto border-t border-border bg-card py-1.5"
    >
      {symbols.map((symbol) => {
        const quote = quotes[symbol];
        if (!quote) return null;
        return (
          <span
            key={symbol}
            title={`Close on ${quote.date}`}
            className="flex items-center gap-2 whitespace-nowrap px-4"
          >
            <span className="type-data text-muted-foreground">{displaySymbol(symbol)}</span>
            <Numeric value={quote.price} format="price" className="text-xs" />
            <Numeric
              value={quote.changePct}
              format="signedPercent"
              tone="signed"
              className="text-xs"
            />
          </span>
        );
      })}
    </div>
  );
}
