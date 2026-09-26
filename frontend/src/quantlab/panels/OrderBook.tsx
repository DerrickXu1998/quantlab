import { Measure } from '../../components/ui/layout';
import type { BookLevel, OrderBook } from '../data/orderBook';
import { Numeric } from '../chrome/Numeric';

function LevelRow({ level, side }: { level: BookLevel; side: 'bid' | 'ask' }) {
  return (
    // py-0.5, not py-1: twenty levels at the looser rhythm ran ~80px past the
    // panel on a 900px viewport, and a book is meant to be dense anyway.
    <div className="relative flex shrink-0 items-center justify-between px-3 py-0.5 font-mono text-[11px] tabular-nums">
      {/* Depth bar: a plain div, width is the level's share of its side. It is
          read against the price/size pair, so it is bounded by the measure
          below rather than by however wide the grid cell happens to be. */}
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
 *
 * Two fitting rules, both of which this panel used to break:
 *
 *   - `min-h-full`, not `h-full`. Inside the panel's scroll region this means
 *     "at least as tall as the viewport, taller if the levels need it", so the
 *     two stacks spread into a roomy panel and the boundary becomes a scroll
 *     edge in a short one. With `h-full` the levels simply overflowed and the
 *     last bid was sliced through the middle.
 *   - a reading measure. The execution grid gives this panel about 1120px; at
 *     that width `justify-between` put PRICE against the left edge of the
 *     screen and SIZE against the right, and reading one level took an eye
 *     movement across the whole workspace.
 */
export function OrderBook({ book }: { book: OrderBook }) {
  return (
    <div data-testid="order-book" className="flex min-h-full flex-col">
      <Measure size="narrow" className="flex min-h-0 flex-1 flex-col">
        {/* Both halves grow, so the spread holds the optical centre of the
            panel however tall it is. The slack lands outside the rules rather
            than inside a bordered box, where it would read as levels the book
            is missing rather than as room around it — and `justify-end` keeps
            the column header on top of its column instead of stranding it at
            the panel's top edge with the slack in between. */}
        <div className="flex flex-1 flex-col justify-end">
          <div className="flex shrink-0 items-center justify-between border-b border-border px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            <span>Price</span>
            <span>Size</span>
          </div>
          <div className="flex shrink-0 flex-col divide-y divide-border">
            {/* Best ask sits at the bottom of the ask stack, next to the spread. */}
            {[...book.asks].reverse().map((level, index) => (
              <LevelRow key={`ask-${index}`} level={level} side="ask" />
            ))}
          </div>
        </div>
        <div
          data-testid="order-book-spread"
          className="flex shrink-0 items-center justify-between border-y border-border px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
        >
          <span>Spread</span>
          <Numeric value={book.spread} className="text-xs" />
        </div>
        <div className="flex flex-1 flex-col divide-y divide-border">
          {book.bids.map((level, index) => (
            <LevelRow key={`bid-${index}`} level={level} side="bid" />
          ))}
        </div>
      </Measure>
    </div>
  );
}
