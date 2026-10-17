import {
  getLiveSession,
  type LiveBar,
  type LiveEvent,
  type LiveLineStatus,
  type LiveSession,
} from '../../api/client';
import { openLiveStream, type LiveStream, type LiveStreamHandlers } from '../../api/live';

/**
 * The browser side of the live market data feed (roadmap 4a).
 *
 * One store per tab, one stream per store: every chart and panel that wants a
 * live price asks this store to watch its symbol, and the store keeps a
 * single `GET /live/stream` open for the union of everything watched. The
 * server allows a user three concurrent streams; a stream per chart would run
 * out at the fourth.
 *
 * Prices are IBKR's and provisional -- display only. Tiingo's end-of-day
 * bars stay the record, and nothing here is written anywhere.
 */

/** Silence longer than this, while the market is open, reads as stale. */
export const STALE_MS = 10_000;
/** How long the store waits for a burst of watch/unwatch calls to settle. */
const DEBOUNCE_MS = 300;
const MAX_BACKOFF_MS = 30_000;

export type FeedConnection = 'idle' | 'connecting' | 'open' | 'offline';

export interface FeedView {
  connection: FeedConnection;
  /** From the server's heartbeat; null until the first one arrives. */
  collector: 'up' | 'down' | null;
  market: 'open' | 'closed' | null;
  /** Client clock (ms) of the last heartbeat. */
  heartbeatAt: number | null;
  /** Why the feed is offline, in words; null otherwise. */
  error: string | null;
  /** The frames come from scripts/live_fake_publish.py, not IBKR. */
  fake: boolean;
}

export interface Quote {
  ts: string;
  last: number | null;
  bid: number | null;
  ask: number | null;
  volume: number | null;
}

/** The minute that has not closed yet, built from ticks as they arrive. */
export interface Forming {
  /** Minute start, unix seconds. */
  start: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  /** The session's cumulative volume when this minute started. */
  volumeAtStart: number | null;
}

export interface SymbolView {
  status: LiveLineStatus;
  detail: string;
  sessionDate: string | null;
  /** Closed minutes, oldest first, one per `ts`. */
  bars: LiveBar[];
  forming: Forming | null;
  quote: Quote | null;
  /** Client clock (ms) of the last tick. */
  tickAt: number | null;
  sessionLoaded: boolean;
  sessionError: string | null;
}

const INITIAL_FEED: FeedView = {
  connection: 'idle',
  collector: null,
  market: null,
  heartbeatAt: null,
  error: null,
  fake: false,
};

function emptySymbol(): SymbolView {
  return {
    status: 'pending',
    detail: '',
    sessionDate: null,
    bars: [],
    forming: null,
    quote: null,
    tickAt: null,
    sessionLoaded: false,
    sessionError: null,
  };
}

/** Unix seconds of a bar or tick timestamp. */
export function epochSeconds(iso: string): number {
  return Math.floor(Date.parse(iso) / 1000);
}

/** Insert or replace a closed minute, keeping the list ordered by `ts`. */
export function upsertBar(bars: LiveBar[], bar: LiveBar): LiveBar[] {
  const at = epochSeconds(bar.ts);
  const out = bars.filter((b) => epochSeconds(b.ts) !== at);
  out.push(bar);
  out.sort((a, b) => epochSeconds(a.ts) - epochSeconds(b.ts));
  return out;
}

/** A session read replaces what it covers and keeps any newer streamed minute. */
export function mergeSession(bars: LiveBar[], session: LiveBar[]): LiveBar[] {
  const last = session.length > 0 ? epochSeconds(session[session.length - 1].ts) : -Infinity;
  let out = [...session];
  for (const bar of bars) if (epochSeconds(bar.ts) > last) out = upsertBar(out, bar);
  return out;
}

/**
 * Fold one tick into the forming minute. A tick in a minute that already
 * closed (its bar has arrived) changes nothing; a tick in a new minute starts
 * a new forming bar at its price.
 */
export function applyTick(
  forming: Forming | null,
  bars: LiveBar[],
  price: number,
  ts: string,
  cumulative: number | null,
  previousCumulative: number | null,
): Forming | null {
  const start = Math.floor(epochSeconds(ts) / 60) * 60;
  const lastBar = bars[bars.length - 1];
  if (lastBar && epochSeconds(lastBar.ts) >= start) return forming;
  if (!forming || forming.start !== start) {
    const volumeAtStart = previousCumulative ?? cumulative;
    return {
      start,
      open: price,
      high: price,
      low: price,
      close: price,
      volume:
        cumulative !== null && volumeAtStart !== null ? Math.max(0, cumulative - volumeAtStart) : 0,
      volumeAtStart,
    };
  }
  return {
    ...forming,
    high: Math.max(forming.high, price),
    low: Math.min(forming.low, price),
    close: price,
    volume:
      cumulative !== null && forming.volumeAtStart !== null
        ? Math.max(0, cumulative - forming.volumeAtStart)
        : forming.volume,
  };
}

export interface LiveFeedDeps {
  open?: (symbols: string[], handlers: LiveStreamHandlers) => LiveStream;
  getSession?: (symbol: string) => Promise<LiveSession>;
  now?: () => number;
  debounceMs?: number;
}

export class LiveFeed {
  private readonly open: NonNullable<LiveFeedDeps['open']>;
  private readonly getSession: NonNullable<LiveFeedDeps['getSession']>;
  private readonly now: () => number;
  private readonly debounceMs: number;

  private readonly refs = new Map<string, number>();
  private readonly symbols = new Map<string, SymbolView>();
  private readonly listeners = new Set<() => void>();
  private feed: FeedView = INITIAL_FEED;

  private stream: LiveStream | null = null;
  private streamKey = '';
  private syncTimer: ReturnType<typeof setTimeout> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private attempts = 0;
  private disposed = false;

  constructor(deps: LiveFeedDeps = {}) {
    this.open = deps.open ?? openLiveStream;
    this.getSession = deps.getSession ?? getLiveSession;
    this.now = deps.now ?? Date.now;
    this.debounceMs = deps.debounceMs ?? DEBOUNCE_MS;
  }

  // --- reading ------------------------------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getFeed = (): FeedView => this.feed;

  getSymbol = (symbol: string): SymbolView | undefined => this.symbols.get(symbol);

  watched(): string[] {
    return [...this.refs.keys()].sort();
  }

  // --- asking -------------------------------------------------------------

  /** Watch a symbol until the returned function is called. Ref-counted. */
  watch(symbol: string): () => void {
    const held = this.refs.get(symbol) ?? 0;
    this.refs.set(symbol, held + 1);
    if (held === 0) {
      if (!this.symbols.has(symbol)) this.setSymbol(symbol, emptySymbol());
      void this.loadSession(symbol);
      this.scheduleSync();
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      const left = (this.refs.get(symbol) ?? 1) - 1;
      if (left > 0) {
        this.refs.set(symbol, left);
        return;
      }
      this.refs.delete(symbol);
      this.scheduleSync();
    };
  }

  /**
   * Close the stream and stop every timer. Reversible with `resume()`:
   * React's StrictMode unmounts and remounts a provider once in development,
   * and a store that stayed dead after that first cleanup silently dropped
   * every session and never connected. Listeners are kept for the same
   * reason -- the components subscribed to it outlive the double-invoke.
   */
  dispose(): void {
    this.disposed = true;
    if (this.syncTimer) clearTimeout(this.syncTimer);
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.syncTimer = null;
    this.retryTimer = null;
    this.stream?.close();
    this.stream = null;
    this.streamKey = '';
  }

  /** Undo `dispose()`: reconnect for whatever is watched and reload sessions. */
  resume(): void {
    if (!this.disposed) return;
    this.disposed = false;
    for (const symbol of this.refs.keys()) void this.loadSession(symbol);
    this.scheduleSync();
  }

  // --- the stream ---------------------------------------------------------

  private scheduleSync(): void {
    if (this.disposed) return;
    if (this.syncTimer) clearTimeout(this.syncTimer);
    this.syncTimer = setTimeout(() => {
      this.syncTimer = null;
      this.sync();
    }, this.debounceMs);
  }

  /** Make the open stream match the watched symbols. */
  private sync(): void {
    if (this.disposed) return;
    const wanted = this.watched();
    // A symbol nobody watches keeps no state.
    for (const symbol of [...this.symbols.keys()]) {
      if (!this.refs.has(symbol)) this.symbols.delete(symbol);
    }
    const key = wanted.join(',');
    if (key === this.streamKey && (this.stream || this.retryTimer)) {
      this.emit();
      return;
    }
    this.stream?.close();
    this.stream = null;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.streamKey = key;
    if (wanted.length === 0) {
      this.setFeed({ ...INITIAL_FEED });
      return;
    }
    this.connect(wanted);
  }

  private connect(symbols: string[]): void {
    this.setFeed({ ...this.feed, connection: 'connecting' });
    const stream = this.open(symbols, {
      onOpen: () => {
        if (this.stream !== stream) return;
        const resumed = this.attempts > 0;
        this.attempts = 0;
        this.setFeed({ ...this.feed, connection: 'open', error: null });
        // Minutes may have closed while the stream was down.
        if (resumed) for (const symbol of symbols) void this.loadSession(symbol);
      },
      onEvent: (event) => {
        if (this.stream !== stream) return;
        this.onEvent(event);
      },
      onEnd: (status, message) => {
        if (this.stream !== stream) return;
        this.stream = null;
        if (status === 401) {
          this.setFeed({ ...this.feed, connection: 'offline', error: message });
          return;
        }
        if (status === 200) {
          // The server's hourly cut-off: reopen at once.
          this.attempts = 0;
          this.connect(symbols);
          return;
        }
        this.setFeed({ ...this.feed, connection: 'offline', error: message });
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempts);
        this.attempts += 1;
        this.retryTimer = setTimeout(() => {
          this.retryTimer = null;
          if (!this.disposed && this.streamKey === symbols.join(',')) this.connect(symbols);
        }, delay);
      },
    });
    this.stream = stream;
  }

  private onEvent(event: LiveEvent): void {
    const fake = event.fake === true || this.feed.fake;
    switch (event.event) {
      case 'heartbeat':
        this.setFeed({
          ...this.feed,
          collector: event.collector ?? null,
          market: event.market ?? null,
          heartbeatAt: this.now(),
          fake,
        });
        return;
      case 'status':
        this.updateSymbol(event.symbol, (s) => ({
          ...s,
          status: event.status ?? s.status,
          detail: event.detail ?? '',
        }));
        return;
      case 'tick':
        if (fake !== this.feed.fake) this.setFeed({ ...this.feed, fake });
        this.updateSymbol(event.symbol, (s) => {
          const ts = event.ts ?? new Date(this.now()).toISOString();
          const quote: Quote = {
            ts,
            last: event.last ?? null,
            bid: event.bid ?? null,
            ask: event.ask ?? null,
            volume: event.volume ?? null,
          };
          const forming =
            quote.last === null
              ? s.forming
              : applyTick(s.forming, s.bars, quote.last, ts, quote.volume, s.quote?.volume ?? null);
          return { ...s, quote, forming, tickAt: this.now() };
        });
        return;
      case 'bar':
        if (!event.bar) return;
        this.updateSymbol(event.symbol, (s) => {
          const bars = upsertBar(s.bars, event.bar!);
          const start = epochSeconds(event.bar!.ts);
          const forming = s.forming && s.forming.start <= start ? null : s.forming;
          return { ...s, bars, forming };
        });
        return;
      case 'backfilled':
        if (event.symbol) void this.loadSession(event.symbol);
        return;
      default:
        return;
    }
  }

  private async loadSession(symbol: string): Promise<void> {
    try {
      const session = await this.getSession(symbol);
      if (this.disposed || !this.refs.has(symbol)) return;
      this.updateSymbol(symbol, (s) => ({
        ...s,
        bars: mergeSession(s.bars, session.bars),
        sessionDate: session.session_date ?? null,
        // The stream's status frames are newer than a session read's.
        status: s.status === 'pending' ? session.status : s.status,
        sessionLoaded: true,
        sessionError: null,
      }));
    } catch (caught) {
      if (this.disposed || !this.refs.has(symbol)) return;
      const message = caught instanceof Error ? caught.message : 'live session unavailable';
      this.updateSymbol(symbol, (s) => ({ ...s, sessionLoaded: true, sessionError: message }));
    }
  }

  // --- state --------------------------------------------------------------

  private updateSymbol(symbol: string | undefined, change: (s: SymbolView) => SymbolView): void {
    if (!symbol) return;
    const current = this.symbols.get(symbol);
    if (!current) return; // not watched
    this.setSymbol(symbol, change(current));
  }

  private setSymbol(symbol: string, view: SymbolView): void {
    this.symbols.set(symbol, view);
    this.emit();
  }

  private setFeed(view: FeedView): void {
    this.feed = view;
    this.emit();
  }

  private emit(): void {
    for (const listener of [...this.listeners]) listener();
  }
}

export type LiveCardState =
  | { kind: 'connecting' }
  | { kind: 'live' }
  | { kind: 'waiting' }
  | { kind: 'stale'; detail: string }
  | { kind: 'closed' }
  | { kind: 'offline'; detail: string }
  | { kind: 'not_subscribed'; detail: string };

/**
 * What one live chart should say about itself, from the feed and its symbol.
 * Ordered from "nothing can arrive" to "prices are arriving": the first that
 * applies wins, so an offline feed never reads as merely quiet.
 */
export function liveCardState(
  feed: FeedView,
  symbol: SymbolView | undefined,
  now: number,
): LiveCardState {
  if (feed.connection === 'offline')
    return { kind: 'offline', detail: feed.error ?? 'The live feed is offline.' };
  if (symbol?.status === 'over_budget') {
    return {
      kind: 'not_subscribed',
      detail: 'No IBKR market-data line free (line budget). Deployed strategies come first.',
    };
  }
  if (symbol?.status === 'unknown_symbol') {
    return { kind: 'not_subscribed', detail: 'IBKR has no matching contract for this symbol.' };
  }
  if (symbol?.status === 'error') {
    return { kind: 'not_subscribed', detail: symbol.detail || 'IBKR refused the subscription.' };
  }
  if (feed.heartbeatAt === null) return { kind: 'connecting' };
  if (now - feed.heartbeatAt > STALE_MS) {
    return { kind: 'stale', detail: 'No word from the server for over 10 s.' };
  }
  if (feed.collector === 'down') {
    return { kind: 'offline', detail: 'The live-ingest collector is down or logged out of IBKR.' };
  }
  if (feed.market === 'closed') return { kind: 'closed' };
  // Ticks arriving are proof the line works, whatever the last status said:
  // the collector writes `active` back on its own schedule.
  if (!symbol || symbol.tickAt === null) return { kind: 'waiting' };
  if (now - symbol.tickAt > STALE_MS) return { kind: 'stale', detail: 'No tick for over 10 s.' };
  return { kind: 'live' };
}
