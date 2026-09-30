import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  getCompanyOverview,
  getPrices,
  listInstruments,
  type Instrument,
  type PriceBar,
} from '../../api/client';
import type { CompanyOverview, FundamentalFact } from '../../api/types';

/**
 * The reads behind the company view.
 *
 * Four states, not three, and the fourth is the one that matters here:
 * `unsupported` means this deployment does not serve the route, which is a
 * different fact from "the backend fell over" and a very different fact from
 * "this company has nothing filed". The same distinction — and the same
 * classifier — as `src/strategies/useFundamentals.ts`, because collapsing it is
 * how a company with a full set of accounts ends up rendered as an empty one
 * while the route that would have said so is still being written.
 */
export type ReadStatus = 'loading' | 'ready' | 'unsupported' | 'error';

export interface Read<T> {
  data: T;
  status: ReadStatus;
  message: string | null;
  reload: () => void;
}

function classify(caught: unknown): { status: ReadStatus; message: string } {
  if (caught instanceof ApiError && caught.status === 404) {
    return { status: 'unsupported', message: 'This backend does not serve it yet.' };
  }
  return {
    status: 'error',
    message: caught instanceof ApiError ? caught.message : 'the warehouse is unreachable',
  };
}

/**
 * Answers already read, kept across unmounts.
 *
 * The shell mounts one destination at a time, so leaving Research drops every
 * read with it, and coming back re-downloaded the catalogue and a full price
 * history before anything drew. Kept here instead, a return shows the last
 * answer at once. Module scope is the lifetime wanted: the tab, not the view.
 *
 * Only successes are kept -- an error must be retried, not replayed -- and the
 * map is bounded, oldest first out, since one price history is ~0.5 MB.
 */
const readCache = new Map<string, { data: unknown; at: number }>();
const READ_CACHE_LIMIT = 24;
/** Older than this is shown at once but re-read behind it. */
export const READ_FRESH_MS = 5 * 60 * 1000;

function remember(key: string, data: unknown) {
  readCache.delete(key);
  readCache.set(key, { data, at: Date.now() });
  while (readCache.size > READ_CACHE_LIMIT) {
    const oldest = readCache.keys().next().value;
    if (oldest === undefined) break;
    readCache.delete(oldest);
  }
}

/**
 * Requests already on the wire. Two readers asking the same question at once
 * -- a remount racing its predecessor, or React's development double effect --
 * share one request instead of downloading the same price history twice.
 */
const inflight = new Map<string, Promise<unknown>>();

function readShared<T>(key: string, load: () => Promise<T>): Promise<T> {
  const pending = inflight.get(key);
  if (pending) return pending as Promise<T>;
  const request = load()
    .then((result) => {
      remember(key, result);
      return result;
    })
    .finally(() => inflight.delete(key));
  inflight.set(key, request);
  return request;
}

/** For tests: each starts from an empty cache. */
export function clearReadCache() {
  readCache.clear();
  inflight.clear();
}

/**
 * One request, keyed by the question it answers.
 *
 * `key` is the whole question written down — `prices:AAPL@..2024-06-30` — so a
 * change of symbol *or* of as-of date re-reads, and nothing else does. A null
 * key is "there is no question yet": it settles immediately on the empty value
 * rather than spending a request to discover that no symbol was chosen.
 *
 * A key answered before is served from {@link readCache} without a loading
 * state; if that answer is older than {@link READ_FRESH_MS} it is re-read
 * quietly behind it. `reload` always goes to the network.
 */
function useKeyedRead<T>(key: string | null, load: () => Promise<T>, empty: T): Read<T> {
  const cachedAtMount = key ? readCache.get(key) : undefined;
  const [data, setData] = useState<T>(cachedAtMount ? (cachedAtMount.data as T) : empty);
  const [status, setStatus] = useState<ReadStatus>(
    !key || cachedAtMount ? 'ready' : 'loading',
  );
  const [message, setMessage] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  // A nonce the effect has not seen yet is an explicit reload.
  const seenNonce = useRef(0);

  // The loader closes over the current symbol and date; `key` is those same
  // values, so the ref carries the fresh closure without widening the deps to a
  // function identity that changes on every render.
  const loadRef = useRef(load);
  loadRef.current = load;
  const emptyRef = useRef(empty);
  emptyRef.current = empty;

  useEffect(() => {
    if (!key) {
      setData(emptyRef.current);
      setStatus('ready');
      setMessage(null);
      return;
    }
    let cancelled = false;
    const forced = nonce !== seenNonce.current;
    seenNonce.current = nonce;
    const cached = forced ? undefined : readCache.get(key);
    if (cached) {
      setData(cached.data as T);
      setMessage(null);
      setStatus('ready');
      if (Date.now() - cached.at < READ_FRESH_MS) return;
    } else {
      setStatus('loading');
    }
    readShared(key, loadRef.current)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setMessage(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        // A failed background re-read keeps the answer already on screen.
        if (cancelled || cached) return;
        const classified = classify(caught);
        setData(emptyRef.current);
        setMessage(classified.message);
        setStatus(classified.status);
      });
    return () => {
      cancelled = true;
    };
  }, [key, nonce]);

  return { data, status, message, reload: () => setNonce((value) => value + 1) };
}

const NO_INSTRUMENTS: Instrument[] = [];
const NO_BARS: PriceBar[] = [];

/**
 * The catalogue the picker searches.
 *
 * Read once for the destination, not per keystroke: 644 rows is one small
 * response, and filtering it in the browser is what makes the first action on
 * this screen feel immediate rather than network-bound.
 */
export function useInstruments(): Read<Instrument[]> {
  return useKeyedRead<Instrument[]>(
    'instruments:all',
    () => listInstruments().then((list) => list.items),
    NO_INSTRUMENTS,
  );
}

/** Everything filed about one name, as of one date. */
export function useCompanyOverview(
  symbol: string | null,
  asOf: string,
): Read<CompanyOverview | null> {
  return useKeyedRead<CompanyOverview | null>(
    symbol && asOf ? `overview:${symbol}@${asOf}` : null,
    () => getCompanyOverview(symbol as string, asOf),
    null,
  );
}

/**
 * Bars up to the as-of date, and not one bar past it.
 *
 * The chart obeys the same cut as the accounts. A price series running to today
 * beside accounts frozen at a past date is a look-ahead chart sitting next to a
 * point-in-time table, and the purpose of this screen is to make that
 * distinction visible rather than to demonstrate it by accident.
 */
export function useCompanyPrices(
  symbol: string | null,
  asOf: string,
  /** First date to read; null for the whole history. */
  start: string | null = null,
): Read<PriceBar[]> {
  return useKeyedRead<PriceBar[]>(
    symbol && asOf ? `prices:${symbol}@${start ?? ''}..${asOf}` : null,
    () => getPrices(symbol as string, start ?? undefined, asOf).then((list) => list.items),
    NO_BARS,
  );
}

/**
 * A filed figure, plus whether it is the row the point-in-time rule selects.
 *
 * The flag is the server's when the server sends it. Where it does not, the
 * fallback is the documented ordering — greatest `period_end`, then greatest
 * `filed_at` — applied per concept. That is a *selection* among rows the server
 * already resolved, never a second implementation of the as-of cut.
 */
export interface AsFiledRow extends FundamentalFact {
  inForce: boolean;
}

export function resolveInForce(facts: FundamentalFact[]): AsFiledRow[] {
  const byConcept = new Map<string, FundamentalFact[]>();
  for (const fact of facts) {
    const rows = byConcept.get(fact.concept);
    if (rows) rows.push(fact);
    else byConcept.set(fact.concept, [fact]);
  }

  const resolved: AsFiledRow[] = [];
  for (const rows of byConcept.values()) {
    const declared = rows.some((row) => row.in_force !== undefined);
    if (declared) {
      for (const row of rows) resolved.push({ ...row, inForce: row.in_force === true });
      continue;
    }
    let winner = rows[0];
    for (const row of rows.slice(1)) {
      if (
        row.period_end > winner.period_end ||
        (row.period_end === winner.period_end && row.filed_at > winner.filed_at)
      ) {
        winner = row;
      }
    }
    for (const row of rows) resolved.push({ ...row, inForce: row === winner });
  }

  // In force first, then alphabetically by concept, so the table reads as the
  // current set of accounts with any superseded rows beneath — rather than as a
  // chronology nobody asked for.
  return resolved.sort((a, b) => {
    if (a.inForce !== b.inForce) return a.inForce ? -1 : 1;
    if (a.concept !== b.concept) return a.concept < b.concept ? -1 : 1;
    return a.filed_at < b.filed_at ? 1 : -1;
  });
}

export function useAsFiledRows(facts: FundamentalFact[]): AsFiledRow[] {
  return useMemo(() => resolveInForce(facts), [facts]);
}

/** Today, written the way the date input writes it. */
export function todayISO(now: Date = new Date()): string {
  const year = now.getFullYear();
  const month = `${now.getMonth() + 1}`.padStart(2, '0');
  const day = `${now.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}
