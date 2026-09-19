export interface Tick {
  symbol: string;
  price: number;
  /** Change against the seed price, i.e. the session's last real close. */
  changePct: number;
  /** Recent prices, for the row sparkline. Bounded, oldest first. */
  history: number[];
}

/** How many points a row sparkline keeps. */
export const HISTORY_LENGTH = 24;

/** Per-tick volatility. Small enough to read as a quote, not a crash. */
const STEP = 0.0025;

/**
 * One step of a random walk.
 *
 * Pure, and takes its randomness as an argument, so a test can hand it a fixed
 * sequence and get a fixed answer. This is invention, not data: there is no
 * streaming endpoint anywhere in the API, and end-of-day bars do not tick.
 */
export function simulateTick(previous: Tick, rng: () => number = Math.random): Tick {
  const drift = (rng() - 0.5) * 2 * STEP;
  const price = Math.max(0.01, previous.price * (1 + drift));
  const seed = previous.history[0] ?? price;

  return {
    symbol: previous.symbol,
    price,
    changePct: seed === 0 ? 0 : price / seed - 1,
    history: [...previous.history, price].slice(-HISTORY_LENGTH),
  };
}

export function seedTick(symbol: string, price: number): Tick {
  return { symbol, price, changePct: 0, history: [price] };
}
