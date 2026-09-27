import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getPrices,
  listInstruments,
  listSignals,
  type Instrument,
  type PriceBar,
} from '../../api/client';
import type { ChartSignal } from '../../components/CandlestickChart';
import { replaceRoute, useRoute } from '../../chrome/router';
import { simulateTick, seedTick } from '../feed/simulateTick';
import { MAX_TICKERS } from './marketModel';

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

export const SIM_TICK_MS = 1000;
const SIM_WINDOW = 300;
const SIM_BACKFILL = 60;

export interface SimPoint {
  /** Unix seconds. */
  time: number;
  value: number;
}

/**
 * A per-chart random walk seeded at the symbol's real last close, one point per
 * second. It exists so the page can show what an intraday view looks like; it
 * is not a quote, and every surface that draws it says so.
 */
export function useSimulatedSeries(
  symbol: string,
  seed: number | null,
  running: boolean,
  rng: () => number = Math.random,
): SimPoint[] {
  const [points, setPoints] = useState<SimPoint[]>([]);
  const tickRef = useRef<ReturnType<typeof seedTick> | null>(null);

  useEffect(() => {
    if (!running || seed === null) {
      setPoints([]);
      tickRef.current = null;
      return;
    }
    // A minute of backfill so the chart opens with a line rather than a dot.
    const now = Math.floor(Date.now() / 1000);
    let tick = seedTick(symbol, seed);
    const initial: SimPoint[] = [];
    for (let i = SIM_BACKFILL; i > 0; i -= 1) {
      initial.push({ time: now - i, value: tick.price });
      tick = simulateTick(tick, rng);
    }
    tickRef.current = tick;
    setPoints(initial);

    const timer = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      const current = tickRef.current;
      if (!current) return;
      const next = simulateTick(current, rng);
      tickRef.current = next;
      setPoints((existing) => {
        const last = existing[existing.length - 1];
        const time = Math.max(Math.floor(Date.now() / 1000), (last?.time ?? 0) + 1);
        return [...existing, { time, value: next.price }].slice(-SIM_WINDOW);
      });
    }, SIM_TICK_MS);

    return () => window.clearInterval(timer);
  }, [symbol, seed, running, rng]);

  return points;
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
