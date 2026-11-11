import { useEffect, useState } from 'react';
import type { Instrument } from '../../api/client';
import { loadInstruments } from '../../research/company/useCompany';
import { loadBars } from '../market/useMarketData';

/** The last stored close of one instrument, and its move on the day. */
export interface Quote {
  price: number;
  /** Last close against the close before it; null with only one bar. */
  changePct: number | null;
  /** The date of the bar the price comes from. */
  date: string;
}

export interface WatchlistState {
  instruments: Instrument[];
  quotes: Record<string, Quote>;
  loading: boolean;
  error: string | null;
}

export const WATCHLIST_SIZE = 8;

/**
 * The names the app opens on: ones a reader recognises, where the dataset has
 * them. The catalogue is alphabetical, so "the first eight" was whatever
 * happened to start with A.
 */
export const FEATURED_SYMBOLS = [
  'AAPL.US',
  'MSFT.US',
  'NVDA.US',
  'AMZN.US',
  'GOOGL.US',
  'META.US',
  'TSLA.US',
  'JPM.US',
] as const;

/** The featured names present in `all`, topped up in catalogue order. */
export function pickWatchlist(all: Instrument[], size = WATCHLIST_SIZE): Instrument[] {
  const bySymbol = new Map(all.map((instrument) => [instrument.symbol, instrument]));
  const featured = FEATURED_SYMBOLS.flatMap((symbol) => bySymbol.get(symbol) ?? []);
  const taken = new Set(featured.map((instrument) => instrument.symbol));
  const rest = all.filter((instrument) => !taken.has(instrument.symbol));
  return [...featured, ...rest].slice(0, size);
}

/**
 * The watchlist and a real quote for each name: its last stored close and the
 * change from the close before. Nothing here moves between loads -- there is
 * no generated tick.
 */
export function useWatchlist(size = WATCHLIST_SIZE): WatchlistState {
  const [state, setState] = useState<WatchlistState>({
    instruments: [],
    quotes: {},
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    loadInstruments()
      .then(async (all) => {
        const instruments = pickWatchlist(all, size);
        const loaded = await Promise.all(
          instruments.map(async (instrument) => {
            try {
              const bars = await loadBars(instrument.symbol);
              const last = bars[bars.length - 1];
              const previous = bars[bars.length - 2];
              if (!last || !(last.close > 0)) return null;
              const quote: Quote = {
                price: last.close,
                changePct: previous && previous.close > 0 ? last.close / previous.close - 1 : null,
                date: last.date,
              };
              return [instrument.symbol, quote] as const;
            } catch {
              return null;
            }
          }),
        );
        if (cancelled) return;
        const quotes: Record<string, Quote> = {};
        for (const entry of loaded) if (entry) quotes[entry[0]] = entry[1];
        setState({ instruments, quotes, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          instruments: [],
          quotes: {},
          loading: false,
          error: error instanceof Error ? error.message : 'prices unavailable',
        });
      });

    return () => {
      cancelled = true;
    };
  }, [size]);

  return state;
}
