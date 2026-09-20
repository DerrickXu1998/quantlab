/**
 * Simulated execution state.
 *
 * A fill is what the order ticket reports: filled in full, at the current
 * simulated price for a market order or at the named price for a limit. There
 * is no matching engine behind it. Positions are netted from the fills in the
 * browser and re-marked against the simulated feed, and both panels say so.
 */

export type Side = 'BUY' | 'SELL';

export interface Fill {
  id: number;
  symbol: string;
  side: Side;
  qty: number;
  price: number;
  /** UTC clock time, for the log. */
  time: string;
}

export interface Position {
  symbol: string;
  /** Signed: positive is long, negative is short. */
  qty: number;
  avgCost: number;
}

/**
 * Nets fills into positions, oldest first. A fill that flips a position
 * through zero re-anchors the average cost at that fill's price.
 */
export function derivePositions(fills: Fill[]): Position[] {
  const book = new Map<string, Position>();
  for (const fill of fills) {
    const signed = fill.side === 'BUY' ? fill.qty : -fill.qty;
    const current = book.get(fill.symbol) ?? { symbol: fill.symbol, qty: 0, avgCost: 0 };

    const qty = current.qty + signed;
    let avgCost = current.avgCost;
    if (current.qty === 0 || Math.sign(current.qty) === Math.sign(signed)) {
      // Adding to (or opening) a position: weighted average in.
      avgCost =
        (Math.abs(current.qty) * current.avgCost + Math.abs(signed) * fill.price) /
        (Math.abs(current.qty) + Math.abs(signed));
    } else if (Math.sign(qty) !== Math.sign(current.qty) && qty !== 0) {
      avgCost = fill.price;
    }
    if (qty === 0) avgCost = 0;

    book.set(fill.symbol, { symbol: fill.symbol, qty, avgCost });
  }
  return [...book.values()].filter((position) => position.qty !== 0);
}
