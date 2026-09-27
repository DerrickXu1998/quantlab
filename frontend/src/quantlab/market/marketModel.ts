import type { PriceBar } from '../../api/client';
import {
  bollinger,
  BOLLINGER_MULT,
  BOLLINGER_PERIOD,
  ema,
  macd,
  MACD_FAST,
  MACD_SIGNAL,
  MACD_SLOW,
  rsi,
  RSI_PERIOD,
  sma,
  type BollingerBand,
  type MacdResult,
} from '../data/indicators';

/**
 * The Market destination's rules, as pure functions.
 *
 * Everything a chart says about itself -- what one bar is, which dates it
 * covers, how far back a point sits from the latest one -- is computed here,
 * so the chart header, the crosshair readout and the tests all agree.
 */

/** Charts on screen at once. Four is the most a 2x2 grid keeps readable. */
export const MAX_TICKERS = 4;

/**
 * Where the numbers come from. The API serves end-of-day bars and has no
 * streaming endpoint, so there is no "live" mode: the alternative to stored
 * history is a simulation, and it is named as one everywhere it appears.
 */
export type DataMode = 'historical' | 'simulated';

export type Interval = '1D' | '1W' | '1M';

export const INTERVALS: { id: Interval; label: string; detail: string }[] = [
  { id: '1D', label: '1D', detail: 'One bar per trading day (end-of-day OHLCV, as stored)' },
  { id: '1W', label: '1W', detail: 'One bar per week, aggregated from the daily bars' },
  { id: '1M', label: '1M', detail: 'One bar per calendar month, aggregated from the daily bars' },
];

export const INTERVAL_NOUN: Record<Interval, string> = {
  '1D': '1 trading day',
  '1W': '1 week',
  '1M': '1 month',
};

export type RangeId = '1M' | '3M' | '6M' | 'YTD' | '1Y' | '5Y' | 'ALL';

export const RANGES: RangeId[] = ['1M', '3M', '6M', 'YTD', '1Y', '5Y', 'ALL'];

export type StudyId = 'sma20' | 'sma50' | 'ema20' | 'bollinger' | 'vwap' | 'rsi' | 'macd' | 'signals';

export interface StudyDef {
  id: StudyId;
  label: string;
  detail: string;
  /** Price pane overlays share the candles' scale; the rest get their own pane. */
  pane: 'price' | 'rsi' | 'macd' | 'markers';
  /** Only historical bars carry what the study needs. */
  historicalOnly?: boolean;
}

export const STUDIES: StudyDef[] = [
  { id: 'sma20', label: 'SMA 20', detail: 'Simple moving average of the last 20 closes', pane: 'price' },
  { id: 'sma50', label: 'SMA 50', detail: 'Simple moving average of the last 50 closes', pane: 'price' },
  { id: 'ema20', label: 'EMA 20', detail: 'Exponential moving average, 20 periods', pane: 'price' },
  {
    id: 'bollinger',
    label: `BB ${BOLLINGER_PERIOD}·${BOLLINGER_MULT}`,
    detail: `Bollinger bands: SMA ${BOLLINGER_PERIOD} ± ${BOLLINGER_MULT} standard deviations`,
    pane: 'price',
  },
  {
    id: 'vwap',
    label: 'VWAP',
    detail: 'Volume-weighted average price, anchored at the start of the visible window',
    pane: 'price',
    historicalOnly: true,
  },
  { id: 'rsi', label: `RSI ${RSI_PERIOD}`, detail: `Relative strength index, ${RSI_PERIOD} periods, own pane`, pane: 'rsi' },
  {
    id: 'macd',
    label: `MACD ${MACD_FAST}·${MACD_SLOW}·${MACD_SIGNAL}`,
    detail: 'MACD line, signal line and histogram, own pane',
    pane: 'macd',
  },
  {
    id: 'signals',
    label: 'Model signals',
    detail: 'Bullish / bearish signals the warehouse models fired, drawn on the bar they fired on',
    pane: 'markers',
    historicalOnly: true,
  },
];

/**
 * The grid for n charts: one fills the workspace, two sit side by side, three
 * and four share a 2x2 (the third of three spans the bottom row). Below `lg`
 * every count stacks, because two charts side by side on a phone are two
 * unreadable charts.
 */
export function gridClasses(count: number): string {
  if (count <= 1) return 'grid-cols-1 grid-rows-1';
  if (count === 2) return 'grid-cols-1 lg:grid-cols-2 lg:grid-rows-1';
  return 'grid-cols-1 lg:grid-cols-2 lg:grid-rows-2';
}

/** The cell class for the i-th of n charts. */
export function cellClasses(index: number, count: number): string {
  return count === 3 && index === 2 ? 'lg:col-span-2' : '';
}

/** Parse a typed list of tickers: commas, spaces, semicolons or newlines. */
export function parseTickers(text: string): string[] {
  const seen = new Set<string>();
  for (const raw of text.split(/[\s,;]+/)) {
    const symbol = raw.trim().toUpperCase();
    if (symbol && symbol !== '<GO>' && symbol !== 'GO') seen.add(symbol);
  }
  return [...seen];
}

/**
 * Resolve typed tickers against the catalogue. `AAPL` finds `AAPL.US` when it
 * is the only listing with that root, which is how people actually type them.
 */
export function resolveTickers(
  typed: string[],
  known: string[],
): { found: string[]; unknown: string[] } {
  const exact = new Set(known);
  const byRoot = new Map<string, string[]>();
  for (const symbol of known) {
    const root = symbol.split('.')[0];
    byRoot.set(root, [...(byRoot.get(root) ?? []), symbol]);
  }
  const found: string[] = [];
  const unknown: string[] = [];
  for (const symbol of typed) {
    if (exact.has(symbol)) found.push(symbol);
    else if (byRoot.get(symbol)?.length === 1) found.push(byRoot.get(symbol)![0]);
    else unknown.push(symbol);
  }
  return { found: [...new Set(found)], unknown };
}

function isoWeekKey(date: string): string {
  const day = new Date(`${date}T00:00:00Z`);
  // Monday of the bar's week, so a week never straddles two keys.
  const offset = (day.getUTCDay() + 6) % 7;
  day.setUTCDate(day.getUTCDate() - offset);
  return day.toISOString().slice(0, 10);
}

/**
 * Aggregate daily bars into weekly or monthly ones: first open, highest high,
 * lowest low, last close, summed volume. A bar is dated by the last trading day
 * it contains, so its date is a real session and the T-offset stays honest.
 */
export function resample(bars: PriceBar[], interval: Interval): PriceBar[] {
  if (interval === '1D') return bars;
  const keyOf = interval === '1W' ? isoWeekKey : (date: string) => date.slice(0, 7);
  const out: PriceBar[] = [];
  let key: string | null = null;
  for (const bar of bars) {
    const next = keyOf(bar.date);
    const current = out[out.length - 1];
    if (key === next && current) {
      current.high = Math.max(current.high, bar.high);
      current.low = Math.min(current.low, bar.low);
      current.close = bar.close;
      current.volume += bar.volume;
      current.date = bar.date;
    } else {
      out.push({ ...bar });
      key = next;
    }
  }
  return out;
}

function shiftMonths(date: string, months: number): string {
  const day = new Date(`${date}T00:00:00Z`);
  day.setUTCMonth(day.getUTCMonth() - months);
  return day.toISOString().slice(0, 10);
}

/** The first date a range keeps, measured back from the latest bar, not today. */
export function rangeStart(lastDate: string, range: RangeId): string | null {
  switch (range) {
    case '1M':
      return shiftMonths(lastDate, 1);
    case '3M':
      return shiftMonths(lastDate, 3);
    case '6M':
      return shiftMonths(lastDate, 6);
    case 'YTD':
      return `${lastDate.slice(0, 4)}-01-01`;
    case '1Y':
      return shiftMonths(lastDate, 12);
    case '5Y':
      return shiftMonths(lastDate, 60);
    default:
      return null;
  }
}

export function sliceRange(bars: PriceBar[], range: RangeId): PriceBar[] {
  const last = bars[bars.length - 1];
  if (!last) return bars;
  const start = rangeStart(last.date, range);
  return start ? bars.filter((bar) => bar.date >= start) : bars;
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export function weekday(date: string): string {
  return WEEKDAYS[new Date(`${date}T00:00:00Z`).getUTCDay()] ?? '';
}

/** Whole calendar days between a bar's date and today -- how stale the data is. */
export function daysOld(date: string, today: Date = new Date()): number {
  const then = Date.parse(`${date}T00:00:00Z`);
  const now = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.max(0, Math.round((now - then) / 86_400_000));
}

/** `T-0` for the latest bar, `T-5` five bars before it. */
export function tOffset(index: number, length: number): string {
  return `T-${Math.max(0, length - 1 - index)}`;
}

export function formatAge(days: number): string {
  if (days === 0) return 'today';
  if (days === 1) return '1 day old';
  return `${days} days old`;
}

export interface Studies {
  sma20?: (number | null)[];
  sma50?: (number | null)[];
  ema20?: (number | null)[];
  bollinger?: BollingerBand[];
  vwap?: (number | null)[];
  rsi?: (number | null)[];
  macd?: MacdResult;
}

/** VWAP from real volume, anchored at the first bar given. */
export function anchoredVwap(bars: Pick<PriceBar, 'high' | 'low' | 'close' | 'volume'>[]): (number | null)[] {
  let priceVolume = 0;
  let volume = 0;
  return bars.map((bar) => {
    const typical = (bar.high + bar.low + bar.close) / 3;
    priceVolume += typical * bar.volume;
    volume += bar.volume;
    return volume > 0 ? priceVolume / volume : null;
  });
}

/**
 * Compute the active studies over the full series, so a moving average at the
 * left edge of a 1M window is not a warm-up gap -- then the caller slices.
 */
export function computeStudies(
  closes: number[],
  active: ReadonlySet<StudyId>,
): Studies {
  const out: Studies = {};
  if (active.has('sma20')) out.sma20 = sma(closes, 20);
  if (active.has('sma50')) out.sma50 = sma(closes, 50);
  if (active.has('ema20')) out.ema20 = ema(closes, 20);
  if (active.has('bollinger')) out.bollinger = bollinger(closes);
  if (active.has('rsi')) out.rsi = rsi(closes);
  if (active.has('macd')) out.macd = macd(closes);
  return out;
}

/** Keep the last `length` points of every study, to line up with a sliced window. */
export function tailStudies(studies: Studies, length: number): Studies {
  const tail = <T,>(values: T[] | undefined) => (values ? values.slice(-length) : undefined);
  return {
    sma20: tail(studies.sma20),
    sma50: tail(studies.sma50),
    ema20: tail(studies.ema20),
    bollinger: tail(studies.bollinger),
    vwap: tail(studies.vwap),
    rsi: tail(studies.rsi),
    macd: studies.macd
      ? {
          line: studies.macd.line.slice(-length),
          signal: studies.macd.signal.slice(-length),
          histogram: studies.macd.histogram.slice(-length),
        }
      : undefined,
  };
}
