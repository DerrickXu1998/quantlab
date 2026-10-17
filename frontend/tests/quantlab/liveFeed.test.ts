import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LiveBar } from '../../src/api/client';
import type { LiveStreamHandlers } from '../../src/api/live';
import {
  applyTick,
  LiveFeed,
  liveCardState,
  mergeSession,
  STALE_MS,
  upsertBar,
  type FeedView,
  type SymbolView,
} from '../../src/quantlab/feed/liveFeed';

function bar(ts: string, close: number, kind: LiveBar['kind'] = 'backfill'): LiveBar {
  return { ts, open: close, high: close, low: close, close, volume: 10, kind };
}

const T0 = '2026-10-15T13:30:00.000Z';
const T1 = '2026-10-15T13:31:00.000Z';
const T2 = '2026-10-15T13:32:00.000Z';

describe('live candles', () => {
  it('replaces a re-sent minute and keeps minutes in order', () => {
    const bars = upsertBar(upsertBar([bar(T1, 2)], bar(T0, 1)), bar(T1, 3));
    expect(bars.map((b) => [b.ts, b.close])).toEqual([
      [T0, 1],
      [T1, 3],
    ]);
  });

  it('lets a session read replace what it covers but keep newer streamed minutes', () => {
    const streamed = [bar(T1, 9, 'rolled'), bar(T2, 5, 'rolled')];
    const merged = mergeSession(streamed, [bar(T0, 1), bar(T1, 2)]);
    expect(merged.map((b) => [b.ts, b.close])).toEqual([
      [T0, 1],
      [T1, 2],
      [T2, 5],
    ]);
  });

  it('forms a minute from ticks and ignores ticks for a minute that already closed', () => {
    let forming = applyTick(null, [bar(T0, 1)], 10, '2026-10-15T13:31:05.000Z', 1000, 900);
    expect(forming).toMatchObject({
      start: Date.parse(T1) / 1000,
      open: 10,
      high: 10,
      low: 10,
      close: 10,
      volume: 100,
    });
    forming = applyTick(forming, [bar(T0, 1)], 12, '2026-10-15T13:31:30.000Z', 1300, 1000);
    forming = applyTick(forming, [bar(T0, 1)], 9, '2026-10-15T13:31:50.000Z', 1500, 1300);
    expect(forming).toMatchObject({ open: 10, high: 12, low: 9, close: 9, volume: 600 });

    // 13:31 has closed: a late tick for it changes nothing.
    const closed = [bar(T0, 1), bar(T1, 9)];
    expect(applyTick(forming, closed, 50, '2026-10-15T13:31:59.000Z', 1600, 1500)).toBe(forming);

    // A tick in the next minute starts a fresh one.
    expect(applyTick(forming, closed, 11, '2026-10-15T13:32:01.000Z', 1700, 1600)).toMatchObject({
      start: Date.parse(T2) / 1000,
      open: 11,
      volume: 100,
    });
  });
});

describe('live card state', () => {
  const now = 1_000_000;
  const feed = (over: Partial<FeedView> = {}): FeedView => ({
    connection: 'open',
    collector: 'up',
    market: 'open',
    heartbeatAt: now - 1000,
    error: null,
    fake: false,
    ...over,
  });
  const symbol = (over: Partial<SymbolView> = {}): SymbolView => ({
    status: 'active',
    detail: '',
    sessionDate: '2026-10-15',
    bars: [],
    forming: null,
    quote: null,
    tickAt: now - 500,
    sessionLoaded: true,
    sessionError: null,
    ...over,
  });

  it('is live only when every link is up and a tick is fresh', () => {
    expect(liveCardState(feed(), symbol(), now).kind).toBe('live');
    // Fresh ticks outrank a status the collector has not written back yet.
    expect(liveCardState(feed(), symbol({ status: 'pending' }), now).kind).toBe('live');
  });

  it('names the first broken link', () => {
    expect(liveCardState(feed({ connection: 'offline', error: 'x' }), symbol(), now)).toEqual({
      kind: 'offline',
      detail: 'x',
    });
    expect(liveCardState(feed(), symbol({ status: 'over_budget' }), now).kind).toBe(
      'not_subscribed',
    );
    expect(liveCardState(feed(), symbol({ status: 'unknown_symbol' }), now).kind).toBe(
      'not_subscribed',
    );
    expect(liveCardState(feed({ heartbeatAt: null }), symbol(), now).kind).toBe('connecting');
    expect(liveCardState(feed({ heartbeatAt: now - STALE_MS - 1 }), symbol(), now).kind).toBe(
      'stale',
    );
    expect(liveCardState(feed({ collector: 'down' }), symbol(), now).kind).toBe('offline');
    expect(liveCardState(feed({ market: 'closed' }), symbol(), now).kind).toBe('closed');
    expect(liveCardState(feed(), symbol({ tickAt: null }), now).kind).toBe('waiting');
    expect(liveCardState(feed(), symbol({ tickAt: now - STALE_MS - 1 }), now).kind).toBe('stale');
  });
});

describe('LiveFeed', () => {
  type Opened = { symbols: string[]; handlers: LiveStreamHandlers; closed: boolean };
  let opened: Opened[];
  let feed: LiveFeed;

  beforeEach(() => {
    vi.useFakeTimers();
    opened = [];
    feed = new LiveFeed({
      debounceMs: 10,
      open: (symbols, handlers) => {
        const stream: Opened = { symbols, handlers, closed: false };
        opened.push(stream);
        return { close: () => (stream.closed = true) };
      },
      getSession: async (symbol) => ({
        symbol,
        session_date: '2026-10-15',
        status: 'pending',
        bars: [bar(T0, 1)],
      }),
    });
  });

  afterEach(() => {
    feed.dispose();
    vi.useRealTimers();
  });

  const settle = () => vi.advanceTimersByTimeAsync(20);

  it('opens one stream for every watched symbol, shared and ref-counted', async () => {
    const a1 = feed.watch('AAPL.US');
    const a2 = feed.watch('AAPL.US');
    feed.watch('MSFT.US');
    await settle();
    expect(opened).toHaveLength(1);
    expect(opened[0].symbols).toEqual(['AAPL.US', 'MSFT.US']);

    a1();
    await settle();
    expect(opened).toHaveLength(1); // AAPL is still watched once

    a2();
    await settle();
    expect(opened[0].closed).toBe(true);
    expect(opened.at(-1)!.symbols).toEqual(['MSFT.US']);
    expect(feed.getSymbol('AAPL.US')).toBeUndefined();
  });

  it("loads each symbol's session and routes events to it", async () => {
    feed.watch('AAPL.US');
    await settle();
    expect(feed.getSymbol('AAPL.US')).toMatchObject({
      sessionLoaded: true,
      sessionDate: '2026-10-15',
    });

    opened[0].handlers.onEvent({
      event: 'status',
      symbol: 'AAPL.US',
      status: 'active',
      detail: '',
    });
    opened[0].handlers.onEvent({
      event: 'tick',
      symbol: 'AAPL.US',
      ts: '2026-10-15T13:31:02.000Z',
      last: 3,
      volume: 1,
    });
    opened[0].handlers.onEvent({
      event: 'tick',
      symbol: 'TSLA.US',
      ts: '2026-10-15T13:31:02.000Z',
      last: 3,
      volume: 1,
    });
    expect(feed.getSymbol('AAPL.US')).toMatchObject({
      status: 'active',
      quote: { last: 3 },
      forming: { close: 3 },
    });
    expect(feed.getSymbol('TSLA.US')).toBeUndefined();
  });

  it('reconnects with backoff, at once after the hourly cut-off, and never after a 401', async () => {
    feed.watch('AAPL.US');
    await settle();

    opened[0].handlers.onEnd(503, 'down');
    expect(feed.getFeed()).toMatchObject({ connection: 'offline', error: 'down' });
    await vi.advanceTimersByTimeAsync(999);
    expect(opened).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(2);
    expect(opened).toHaveLength(2);

    opened[1].handlers.onEnd(503, 'down again');
    await vi.advanceTimersByTimeAsync(1500);
    expect(opened).toHaveLength(2); // second wait is 2 s
    await vi.advanceTimersByTimeAsync(600);
    expect(opened).toHaveLength(3);

    opened[2].handlers.onOpen?.();
    opened[2].handlers.onEnd(200, 'ended');
    expect(opened).toHaveLength(4);

    opened[3].handlers.onEnd(401, 'expired');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(opened).toHaveLength(4);
    expect(feed.getFeed().connection).toBe('offline');
  });

  it('comes back after dispose and resume, as StrictMode does on mount', async () => {
    feed.watch('AAPL.US');
    feed.dispose();
    feed.resume();
    await settle();

    expect(opened.at(-1)).toMatchObject({ symbols: ['AAPL.US'], closed: false });
    expect(feed.getSymbol('AAPL.US')).toMatchObject({ sessionLoaded: true });
  });

  it("ignores a closed stream's late events", async () => {
    feed.watch('AAPL.US');
    await settle();
    const first = opened[0];
    feed.watch('MSFT.US');
    await settle();
    first.handlers.onEvent({
      event: 'tick',
      symbol: 'AAPL.US',
      ts: '2026-10-15T13:31:02.000Z',
      last: 99,
    });
    expect(feed.getSymbol('AAPL.US')?.quote).toBeNull();
  });
});
