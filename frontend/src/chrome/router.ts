import { useCallback, useSyncExternalStore } from 'react';

/**
 * The app's six destinations, addressed by hash.
 *
 * A hash, not a router library: there are six flat destinations and a small
 * set of handoff parameters, and pulling in react-router would add a
 * dependency and force every test into a MemoryRouter for no gain. The hash
 * still gives deep links, refresh-safe state, and a working back button.
 */
export type Destination =
  | 'overview'
  | 'research'
  | 'strategies'
  | 'replay'
  | 'market'
  | 'execution';

export const DESTINATIONS: readonly Destination[] = [
  'overview',
  'research',
  'strategies',
  'replay',
  'market',
  'execution',
];

export interface Route {
  destination: Destination;
  /** Query params on the hash — the cross-destination handoff channel. */
  params: URLSearchParams;
  /** False when the raw hash was legacy or unknown and had to be mapped. */
  canonical: boolean;
}

/** Pre-shell hashes. `#/` was the Signal Viewer, `#/lab` the Quant Lab. */
const LEGACY: Record<string, Destination> = {
  '': 'overview',
  lab: 'overview',
};

export function hashFor(destination: Destination, params?: Record<string, string>): string {
  const query = params ? new URLSearchParams(params).toString() : '';
  return `#/${destination}${query ? `?${query}` : ''}`;
}

function parse(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '');
  const separator = raw.indexOf('?');
  const key = (separator === -1 ? raw : raw.slice(0, separator)).split('/')[0] ?? '';
  const query = separator === -1 ? '' : raw.slice(separator + 1);
  if ((DESTINATIONS as readonly string[]).includes(key)) {
    return { destination: key as Destination, params: new URLSearchParams(query), canonical: true };
  }
  return {
    destination: LEGACY[key] ?? 'overview',
    params: new URLSearchParams(query),
    canonical: false,
  };
}

// useSyncExternalStore requires getSnapshot to be referentially stable between
// changes, so the parsed route is cached against the raw hash string.
let cachedHash: string | null = null;
let cachedRoute: Route | null = null;

function read(): Route {
  const hash = window.location.hash;
  if (hash !== cachedHash || cachedRoute === null) {
    cachedHash = hash;
    cachedRoute = parse(hash);
  }
  return cachedRoute;
}

const subscribers = new Set<() => void>();

function notify() {
  cachedHash = null;
  cachedRoute = null;
  for (const subscriber of subscribers) subscriber();
}

function subscribe(onChange: () => void): () => void {
  subscribers.add(onChange);
  if (subscribers.size === 1) window.addEventListener('hashchange', notify);
  return () => {
    subscribers.delete(onChange);
    if (subscribers.size === 0) window.removeEventListener('hashchange', notify);
  };
}

/** Navigate, adding a history entry — this is what back/forward walks through. */
export function navigate(destination: Destination, params?: Record<string, string>): void {
  window.location.hash = hashFor(destination, params);
}

/**
 * Rewrite the address without a history entry. Used to canonicalise legacy
 * hashes (`#/`, `#/lab`) — replaceState does not fire hashchange, so
 * subscribers are notified explicitly.
 */
export function replaceRoute(destination: Destination, params: URLSearchParams): void {
  const query = params.toString();
  window.history.replaceState(null, '', `#/${destination}${query ? `?${query}` : ''}`);
  notify();
}

export function useRoute(): Route {
  // getServerSnapshot is the same read: there is no SSR here, but
  // useSyncExternalStore insists on one and hydration must not disagree.
  return useSyncExternalStore(subscribe, read, read);
}

export function useNavigate(): (destination: Destination, params?: Record<string, string>) => void {
  return useCallback((destination: Destination, params?: Record<string, string>) => {
    navigate(destination, params);
  }, []);
}
