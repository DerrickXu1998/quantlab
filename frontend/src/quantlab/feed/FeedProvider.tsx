import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { seedTick, simulateTick, type Tick } from './simulateTick';

export const FEED_INTERVAL_MS = 800;

export type FeedStatus = 'connecting' | 'live' | 'stalled';

interface FeedStore {
  get: (symbol: string) => Tick | undefined;
  subscribe: (symbol: string, listener: () => void) => () => void;
  status: FeedStatus;
  symbols: string[];
}

const FeedContext = createContext<FeedStore | null>(null);

export interface FeedProviderProps {
  /** Seed prices: the real last close per symbol, from GET /instruments/{s}/prices. */
  seeds: Record<string, number>;
  children: ReactNode;
  intervalMs?: number;
  rng?: () => number;
}

/**
 * A stand-in for a market data feed.
 *
 * QuantLab has no streaming endpoint and stores end-of-day bars, so nothing
 * here is a real quote. The walk is seeded from each instrument's real last
 * close, which makes the levels plausible and the motion entirely invented —
 * every panel that shows it is tagged accordingly.
 *
 * One interval for the whole surface, with per-symbol subscriptions, so a tick
 * re-renders one row rather than the page.
 */
export function FeedProvider({
  seeds,
  children,
  intervalMs = FEED_INTERVAL_MS,
  rng = Math.random,
}: FeedProviderProps) {
  const ticks = useRef(new Map<string, Tick>());
  const listeners = useRef(new Map<string, Set<() => void>>());
  const [status, setStatus] = useState<FeedStatus>('connecting');

  const symbols = useMemo(() => Object.keys(seeds).sort(), [seeds]);

  useEffect(() => {
    // Re-seed whenever the selection changes; a symbol that left keeps no state.
    const next = new Map<string, Tick>();
    for (const symbol of symbols) next.set(symbol, seedTick(symbol, seeds[symbol]));
    ticks.current = next;
    for (const set of listeners.current.values()) for (const fn of set) fn();
    setStatus(symbols.length > 0 ? 'live' : 'connecting');
  }, [symbols, seeds]);

  useEffect(() => {
    if (symbols.length === 0) return;

    const timer = window.setInterval(() => {
      // Nothing is watching a backgrounded tab; burning a timer on it is waste.
      if (typeof document !== 'undefined' && document.hidden) return;
      for (const symbol of symbols) {
        const current = ticks.current.get(symbol);
        if (!current) continue;
        ticks.current.set(symbol, simulateTick(current, rng));
        const set = listeners.current.get(symbol);
        if (set) for (const fn of set) fn();
      }
    }, intervalMs);

    return () => window.clearInterval(timer);
  }, [symbols, intervalMs, rng]);

  const subscribe = useCallback((symbol: string, listener: () => void) => {
    let set = listeners.current.get(symbol);
    if (!set) {
      set = new Set();
      listeners.current.set(symbol, set);
    }
    set.add(listener);
    return () => {
      set?.delete(listener);
    };
  }, []);

  const get = useCallback((symbol: string) => ticks.current.get(symbol), []);

  const store = useMemo<FeedStore>(
    () => ({ get, subscribe, status, symbols }),
    [get, subscribe, status, symbols],
  );

  return <FeedContext.Provider value={store}>{children}</FeedContext.Provider>;
}

export function useFeedStatus(): FeedStatus {
  return useContext(FeedContext)?.status ?? 'stalled';
}

export function useFeedSymbols(): string[] {
  return useContext(FeedContext)?.symbols ?? [];
}

/** Subscribes to one symbol only, so an unrelated tick costs nothing. */
export function useTick(symbol: string): Tick | undefined {
  const store = useContext(FeedContext);

  const subscribe = useCallback(
    (listener: () => void) => store?.subscribe(symbol, listener) ?? (() => {}),
    [store, symbol],
  );
  const snapshot = useCallback(() => store?.get(symbol), [store, symbol]);

  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
