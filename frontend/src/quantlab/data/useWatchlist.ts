import { useEffect, useState } from 'react';
import { getPrices, listInstruments, type Instrument } from '../../api/client';

export interface WatchlistState {
  instruments: Instrument[];
  /** Real last close per symbol; the feed walks away from these. */
  seeds: Record<string, number>;
  loading: boolean;
  error: string | null;
  /** Re-runs the instrument load after an error. */
  retry: () => void;
}

/** How many names the rail carries. Enough to fill it, few enough to read. */
export const WATCHLIST_SIZE = 8;

/**
 * The watchlist: real instruments at their real last close.
 *
 * The levels are genuine; only the per-second movement on top of them is
 * invented, because the API serves end-of-day bars and has no stream.
 *
 * Seeds — and therefore the simulated feed — cover equities only. A macro
 * instrument's bars are a daily value series (a yield, a percent, index
 * points), not a price: random-walking a Treasury yield once a second would
 * be a lie with a sparkline on it. Macro rows show history, never ticks.
 */
export function useWatchlist(size = WATCHLIST_SIZE): WatchlistState {
  const [state, setState] = useState<Omit<WatchlistState, 'retry'>>({
    instruments: [],
    seeds: {},
    loading: true,
    error: null,
  });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState((current) => ({ ...current, loading: true, error: null }));

    listInstruments()
      .then(async (list) => {
        const instruments = list.items.slice(0, size);
        const closes = await Promise.all(
          instruments.map(async (instrument) => {
            try {
              const bars = await getPrices(instrument.symbol);
              const last = bars.items[bars.items.length - 1];
              return [instrument.symbol, last ? last.close : 0] as const;
            } catch {
              // One unreadable symbol must not blank the whole rail.
              return [instrument.symbol, 0] as const;
            }
          }),
        );
        if (cancelled) return;
        const seeds: Record<string, number> = {};
        const macro = new Set(
          instruments.filter((instrument) => instrument.kind === 'macro').map((i) => i.symbol),
        );
        for (const [symbol, close] of closes) {
          if (close > 0 && !macro.has(symbol)) seeds[symbol] = close;
        }
        setState({ instruments, seeds, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          instruments: [],
          seeds: {},
          loading: false,
          error: error instanceof Error ? error.message : 'feed unavailable',
        });
      });

    return () => {
      cancelled = true;
    };
  }, [size, nonce]);

  return { ...state, retry: () => setNonce((n) => n + 1) };
}
