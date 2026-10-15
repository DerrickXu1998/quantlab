import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getPrices,
  listInstruments,
  listSignals,
  type Instrument,
  type PriceBar,
} from '../../api/client';
import type { ChartSignal } from '../../components/CandlestickChart';
import { replaceRoute, useRoute } from '../../chrome/router';
import { useLiveSymbol, useNow } from '../feed/LiveFeedProvider';
import { liveCardState, type FeedView, type LiveCardState, type Quote, type SymbolView } from '../feed/liveFeed';
import { liveCandles, MAX_TICKERS, type Candle } from './marketModel';

type Load<T> = { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; message: string };

function message(caught: unknown, fallback: string): string {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

/**
 * Every instrument the warehouse serves -- not the eight the header's feed
 * seeds. The old rail was that eight-name watchlist, which is why the Market
 * page could only ever chart a fraction of the universe.
 */
export function useInstrumentCatalog(fallback: Instrument[]): Load<Instrument[]> {
  const [state, setState] = useState<Load<Instrument[]>>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    listInstruments()
      .then((list) => {
        if (!cancelled) setState({ status: 'ready', data: list.items });
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        // Fall back to whatever the shell already has rather than a blank rail.
        if (fallback.length > 0) setState({ status: 'ready', data: fallback });
        else setState({ status: 'error', message: message(caught, 'instrument list unavailable') });
      });
    return () => {
      cancelled = true;
    };
    // The fallback only matters on failure; refetching when it changes would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return state;
}

// Bars are immutable end-of-day history for the session, so one fetch per
// symbol serves every range, interval and re-mount.
const barCache = new Map<string, Promise<PriceBar[]>>();

export function clearBarCache(): void {
  barCache.clear();
}

function loadBars(symbol: string): Promise<PriceBar[]> {
  let pending = barCache.get(symbol);
  if (!pending) {
    pending = getPrices(symbol).then((result) =>
      [...result.items].sort((a, b) => a.date.localeCompare(b.date)),
    );
    pending.catch(() => barCache.delete(symbol));
    barCache.set(symbol, pending);
  }
  return pending;
}

export function useDailyBars(symbol: string): Load<PriceBar[]> {
  const [state, setState] = useState<Load<PriceBar[]>>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    loadBars(symbol)
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', data });
      })
      .catch((caught: unknown) => {
        if (!cancelled) setState({ status: 'error', message: message(caught, 'price history unavailable') });
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return state;
}

/** The models' signals for one symbol, as chart markers labelled by rule. */
export function useModelSignals(symbol: string, enabled: boolean): ChartSignal[] {
  const [signals, setSignals] = useState<ChartSignal[]>([]);

  useEffect(() => {
    if (!enabled) {
      setSignals([]);
      return;
    }
    let cancelled = false;
    listSignals({ instrument: symbol, limit: 1000, sort: 'date_asc' })
      .then((result) => {
        if (cancelled) return;
        setSignals(
          result.items.map((signal) => ({
            date: signal.date.slice(0, 10),
            direction: signal.direction,
            label: signal.rule_name,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setSignals([]);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, enabled]);

  return signals;
}

/** How often a live chart re-reads the clock, for its staleness check. */
const LIVE_CLOCK_MS = 1000;

export interface LiveSeries {
  /** 1-minute candles from the open, the newest one forming tick by tick. */
  candles: Candle[];
  quote: Quote | null;
  state: LiveCardState;
  feed: FeedView;
  view: SymbolView | undefined;
}

/**
 * Today's live prices for one symbol, while `enabled`: the session's minutes
 * from the open (GET /live/{symbol}/session), then about a tick a second over
 * the tab's one live stream. IBKR's prices, provisional; every surface that
 * draws them says so.
 */
export function useLiveSeries(symbol: string, enabled: boolean): LiveSeries {
  const { feed, view } = useLiveSymbol(symbol, enabled);
  const now = useNow(LIVE_CLOCK_MS, enabled);
  const candles = useMemo(() => (view ? liveCandles(view.bars, view.forming) : []), [view]);
  return {
    candles,
    quote: view?.quote ?? null,
    state: liveCardState(feed, view, now),
    feed,
    view,
  };
}

/**
 * The charted tickers, held in the address (`#/market?symbols=A,B`) so a view
 * survives a refresh and can be linked -- the same handoff channel Research
 * uses. At most MAX_TICKERS; extra symbols in a pasted link are dropped.
 */
export function useChartSelection(): {
  selected: string[];
  set: (symbols: string[]) => void;
  toggle: (symbol: string) => void;
  remove: (symbol: string) => void;
} {
  const route = useRoute();
  const raw = route.params.get('symbols') ?? '';
  const selected = useMemo(
    () => [...new Set(raw.split(',').filter(Boolean))].slice(0, MAX_TICKERS),
    [raw],
  );

  const set = useCallback(
    (symbols: string[]) => {
      const params = new URLSearchParams(route.params);
      const next = [...new Set(symbols)].slice(0, MAX_TICKERS);
      if (next.length > 0) params.set('symbols', next.join(','));
      else params.delete('symbols');
      replaceRoute('market', params);
    },
    [route.params],
  );

  const toggle = useCallback(
    (symbol: string) => {
      if (selected.includes(symbol)) set(selected.filter((s) => s !== symbol));
      else if (selected.length < MAX_TICKERS) set([...selected, symbol]);
    },
    [selected, set],
  );

  const remove = useCallback(
    (symbol: string) => set(selected.filter((s) => s !== symbol)),
    [selected, set],
  );

  return { selected, set, toggle, remove };
}

export interface CustomUniverse {
  name: string;
  symbols: string[];
}

const UNIVERSE_KEY = 'quantlab.market.universes';

function readUniverses(): CustomUniverse[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(UNIVERSE_KEY) ?? '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is CustomUniverse =>
        typeof item?.name === 'string' && Array.isArray(item?.symbols),
    );
  } catch {
    return [];
  }
}

/**
 * Watchlists the user builds for this page. Kept in the browser: the API can
 * publish a universe but does not serve its members back, so a saved list
 * could not be reopened from the server.
 */
export function useCustomUniverses(): {
  universes: CustomUniverse[];
  save: (universe: CustomUniverse) => void;
  remove: (name: string) => void;
} {
  const [universes, setUniverses] = useState<CustomUniverse[]>(readUniverses);

  const persist = useCallback((next: CustomUniverse[]) => {
    setUniverses(next);
    try {
      window.localStorage.setItem(UNIVERSE_KEY, JSON.stringify(next));
    } catch {
      // Private mode or a full quota: the list still works for this session.
    }
  }, []);

  const save = useCallback(
    (universe: CustomUniverse) =>
      persist([...universes.filter((u) => u.name !== universe.name), universe]),
    [universes, persist],
  );

  const remove = useCallback(
    (name: string) => persist(universes.filter((u) => u.name !== name)),
    [universes, persist],
  );

  return { universes, save, remove };
}
