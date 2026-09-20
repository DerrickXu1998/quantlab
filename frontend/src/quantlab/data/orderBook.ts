/**
 * The simulated order book.
 *
 * There is no execution backend and no market data stream, so the book is
 * generated around the simulated feed's current price. It is a pure function
 * of that price — a tick moves the price, which reseeds the jitter, which is
 * why the levels and sizes shimmer on every tick without any timers of its own.
 */

export interface BookLevel {
  price: number;
  size: number;
  /** Size relative to the deepest level on the same side, 0–1, for depth bars. */
  depth: number;
}

export interface OrderBook {
  /** Best bid first. */
  bids: BookLevel[];
  /** Best ask first. */
  asks: BookLevel[];
  mid: number;
  spread: number;
}

export const BOOK_LEVELS = 10;

/** A deterministic hash → [0, 1), so the same mid always draws the same book. */
function jitter(seed: number): number {
  let h = (seed >>> 0) || 1;
  h ^= h << 13;
  h ^= h >>> 17;
  h ^= h << 5;
  return (h >>> 0) / 4294967296;
}

export function buildOrderBook(mid: number, levels = BOOK_LEVELS): OrderBook {
  // Quantized so sub-cent noise does not reseed the book within a tick.
  const base = Math.round(mid * 10000);
  const spread = mid * (0.0004 + jitter(base) * 0.0008);

  const build = (side: 1 | -1): BookLevel[] => {
    const rows: BookLevel[] = [];
    let max = 0;
    for (let i = 0; i < levels; i += 1) {
      const stepJitter = jitter(base + (side > 0 ? 1000 : 2000) + i * 7);
      const sizeJitter = jitter(base + (side > 0 ? 3000 : 4000) + i * 13);
      const price = mid + side * (spread / 2 + (i + stepJitter) * mid * 0.0003);
      const size = Math.round(50 + sizeJitter * 950);
      if (size > max) max = size;
      rows.push({ price, size, depth: 0 });
    }
    return rows.map((row) => ({ ...row, depth: max === 0 ? 0 : row.size / max }));
  };

  return { bids: build(-1), asks: build(1), mid, spread };
}
