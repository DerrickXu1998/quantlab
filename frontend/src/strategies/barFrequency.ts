/**
 * Signal bar frequency: the choices, what each means, and how big a run is.
 *
 * The backend refuses an oversized run before reading any data
 * (`research/runner.py`); the same arithmetic here lets the form say so before
 * the request is sent, rather than after a round trip. The limits mirror the
 * backend's and are the ones the README documents.
 */

export const BAR_FREQUENCIES = ['1d', '1h', '15m', '5m'] as const;

export type BarFrequency = (typeof BAR_FREQUENCIES)[number];

export const BAR_FREQUENCY_LABELS: Record<BarFrequency, string> = {
  '1d': 'Daily',
  '1h': '1 hour',
  '15m': '15 minutes',
  '5m': '5 minutes',
};

/** Bars in one regular session (09:30–16:00 New York). */
export const BARS_PER_SESSION: Record<BarFrequency, number> = {
  '1d': 1,
  '1h': 7,
  '15m': 26,
  '5m': 78,
};

export const BAR_FREQUENCY_EXPLAINERS: Record<BarFrequency, string> = {
  '1d': 'Signals on daily bars: one decision per session, at its close.',
  '1h':
    'Signals on hourly bars built from the minute feed: 7 a session. Every count of days in the rules and execution criteria counts bars instead.',
  '15m':
    'Signals on 15-minute bars built from the minute feed: 26 a session. Every count of days in the rules and execution criteria counts bars instead.',
  '5m':
    'Signals on 5-minute bars built from the minute feed: 78 a session. Every count of days in the rules and execution criteria counts bars instead.',
};

/** The first session of the minute feed intraday bars are built from. */
export const MINUTE_DATA_START = '2016-12-12';

/** Backend limits (research/runner.py). */
export const MAX_INTRADAY_BARS = 6_000_000;
export const MAX_DAILY_INSTRUMENT_DAYS = 8_400_000;

/**
 * Seconds per million intraday bars for each phase of a run, measured on the
 * production VM (2026-10-03, 5m bars, 29 symbols x 2024 = 569k bars):
 * RSI mean reversion (2 components) 21 s, S2 regime reversion (4) 53 s.
 * Reading is the small part; computing each component's signals over every
 * bar is most of it, so the estimate grows with the strategy, not just the data.
 */
const READ_S_PER_M = 5;
const BACKTEST_S_PER_M = 6;
const SIGNALS_S_PER_M_PER_COMPONENT = 18;

export interface RunTime {
  read: number;
  signals: number;
  backtest: number;
  total: number;
}

export function isIntraday(frequency: BarFrequency): boolean {
  return frequency !== '1d';
}

/** Weekdays in [start, end], both ISO dates; 0 for an empty or invalid window. */
export function weekdaysBetween(start: string, end: string): number {
  const from = Date.parse(`${start}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return 0;
  const days = Math.round((to - from) / 86_400_000) + 1;
  const fullWeeks = Math.floor(days / 7);
  let count = fullWeeks * 5;
  const firstDay = new Date(from).getUTCDay();
  for (let i = 0; i < days % 7; i += 1) {
    const day = (firstDay + i) % 7;
    if (day !== 0 && day !== 6) count += 1;
  }
  return count;
}

export interface RunSize {
  /** Bars the run would hold, before the strategy's warm-up. */
  bars: number;
  /** Estimated wall time of an intraday run, by phase; null for daily runs. */
  time: RunTime | null;
  /** Why the backend would refuse it, or null when it fits. */
  blocker: string | null;
}

export function runSize(
  symbols: number,
  start: string,
  end: string,
  frequency: BarFrequency,
  components = 1,
): RunSize {
  const bars = symbols * weekdaysBetween(start, end) * BARS_PER_SESSION[frequency];
  if (!isIntraday(frequency)) {
    const instrumentDays = symbols * calendarDays(start, end);
    return {
      bars,
      time: null,
      blocker:
        instrumentDays > MAX_DAILY_INSTRUMENT_DAYS
          ? `About ${instrumentDays.toLocaleString()} instrument-days exceeds the limit of ${MAX_DAILY_INSTRUMENT_DAYS.toLocaleString()}; select fewer symbols or a shorter window.`
          : null,
    };
  }
  let blocker: string | null = null;
  if (start < MINUTE_DATA_START) {
    blocker = `Intraday bars start on ${MINUTE_DATA_START}; move the start date to it or later.`;
  } else if (bars > MAX_INTRADAY_BARS) {
    blocker = `About ${bars.toLocaleString()} ${frequency} bars exceeds the limit of ${MAX_INTRADAY_BARS.toLocaleString()} per run; use a coarser frequency, fewer symbols or a shorter window.`;
  }
  return {
    bars,
    time: runTime(bars, components),
    blocker,
  };
}

function runTime(bars: number, components: number): RunTime {
  const millions = bars / 1_000_000;
  const read = millions * READ_S_PER_M;
  const signals = millions * SIGNALS_S_PER_M_PER_COMPONENT * Math.max(1, components);
  const backtest = millions * BACKTEST_S_PER_M;
  return { read, signals, backtest, total: read + signals + backtest };
}

/** "about 45 s" / "about 3 min", for an estimate that is a guide, not a promise. */
export function formatDuration(seconds: number): string {
  if (seconds < 1) return 'under a second';
  if (seconds < 90) return `${Math.round(seconds)} s`;
  return `${Math.round(seconds / 60)} min`;
}

function calendarDays(start: string, end: string): number {
  const from = Date.parse(`${start}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return 0;
  return Math.round((to - from) / 86_400_000) + 1;
}
