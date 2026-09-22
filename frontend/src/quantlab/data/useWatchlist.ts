import { useEffect, useState } from 'react';
import { getPrices, listInstruments, type Instrument } from '../../api/client';

export interface WatchlistState {
  instruments: Instrument[];
  /** Real last close per symbol; the feed walks away from these. */
  seeds: Record<string, number>;
  loading: boolean;
  error: string | null;
}

/** How many names the rail carries. Enough to fill it, few enough to read. */
export const WATCHLIST_SIZE = 8;

/**
 * The watchlist: real instruments at their real last close.
 *
 * The levels are genuine; only the per-second movement on top of them is
 * invented, because the API serves end-of-day bars and has no stream.
 */
export function useWatchlist(size = WATCHLIST_SIZE): WatchlistState {
  const [state, setState] = useState<WatchlistState>({
    instruments: [],
    seeds: {},
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

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
        for (const [symbol, close] of closes) if (close > 0) seeds[symbol] = close;
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
  }, [size]);

  return state;
}
