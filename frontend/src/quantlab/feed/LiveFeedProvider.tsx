import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { LiveFeed, type FeedView, type SymbolView } from './liveFeed';

const LiveFeedContext = createContext<LiveFeed | null>(null);

// Outside a provider (a component rendered on its own, in a test), one shared
// store still gives every caller the same single stream.
let fallback: LiveFeed | null = null;

/** One live feed store for everything below it -- one stream per tab. */
export function LiveFeedProvider({ feed, children }: { feed?: LiveFeed; children: ReactNode }) {
  const [store] = useState(() => feed ?? new LiveFeed());
  useEffect(() => {
    if (feed) return undefined;
    // Resume as well as dispose: StrictMode runs this cleanup once on mount.
    store.resume();
    return () => store.dispose();
  }, [feed, store]);
  return <LiveFeedContext.Provider value={store}>{children}</LiveFeedContext.Provider>;
}

export function useLiveFeedStore(): LiveFeed {
  const store = useContext(LiveFeedContext);
  if (store) return store;
  fallback ??= new LiveFeed();
  return fallback;
}

/**
 * Watch one symbol while mounted (and `enabled`), and re-render on its
 * changes. Watching is ref-counted in the store, so two charts of one symbol
 * share a line and a subscription.
 */
export function useLiveSymbol(
  symbol: string,
  enabled = true,
): { feed: FeedView; view: SymbolView | undefined } {
  const store = useLiveFeedStore();
  useEffect(() => (enabled ? store.watch(symbol) : undefined), [store, symbol, enabled]);
  const feed = useSyncExternalStore(store.subscribe, store.getFeed, store.getFeed);
  const view = useSyncExternalStore(
    store.subscribe,
    () => (enabled ? store.getSymbol(symbol) : undefined),
    () => undefined,
  );
  return { feed, view };
}

/** The wall clock, re-read every `intervalMs` while `enabled`: for staleness. */
export function useNow(intervalMs: number, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs, enabled]);
  return now;
}
