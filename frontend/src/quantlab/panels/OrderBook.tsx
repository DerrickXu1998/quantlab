import type { BookLevel, OrderBook } from '../data/orderBook';
import { Numeric } from '../chrome/Numeric';

function LevelRow({ level, side }: { level: BookLevel; side: 'bid' | 'ask' }) {
  return (
    <div className="relative flex items-center justify-between px-3 py-1 font-mono text-[11px] tabular-nums">
      {/* Depth bar: a plain div, width is the level's share of its side. */}
      <span
        aria-hidden="true"
        className={`absolute inset-y-0 ${side === 'bid' ? 'right-0 bg-primary/10' : 'left-0 bg-muted-foreground/10'}`}
        style={{ width: `${Math.round(level.depth * 100)}%` }}
      />
      <span className={`relative ${side === 'bid' ? 'text-primary' : 'text-foreground'}`}>
        <Numeric value={level.price} />
      </span>
      <span className="relative text-muted-foreground">
        <Numeric value={level.size} format="integer" />
      </span>
    </div>
  );
}

/**
 * The book around the simulated mid: asks above, bids below, spread between.
 * Everything here is generated — the panel it sits in carries the tag.
 */
export function OrderBook({ book }: { book: OrderBook }) {
  return (
    <div data-testid="order-book" className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        <span>Price</span>
        <span>Size</span>
      </div>
      <div className="flex flex-1 flex-col justify-end divide-y divide-border border-y border-border">
        {/* Best ask sits at the bottom of the ask stack, next to the spread. */}
        {[...book.asks].reverse().map((level, index) => (
          <LevelRow key={`ask-${index}`} level={level} side="ask" />
        ))}
      </div>
      <div
        data-testid="order-book-spread"
        className="flex items-center justify-between px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
      >
        <span>Spread</span>
        <Numeric value={book.spread} className="text-[11px]" />
      </div>
      <div className="flex flex-1 flex-col divide-y divide-border border-y border-border">
        {book.bids.map((level, index) => (
          <LevelRow key={`bid-${index}`} level={level} side="bid" />
        ))}
      </div>
    </div>
  );
}
