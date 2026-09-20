/**
 * Standard indicator math over a rolling price series.
 *
 * Pure functions, null-padded to the input length so every output aligns with
 * the series it was computed from — index i of an output is the value at tick
 * i, and null means "not enough history yet". They run on the simulated feed's
 * prices, so the curves are as invented as the ticks underneath them; the math
 * itself is the textbook version.
 */

export const RSI_PERIOD = 14;
export const MACD_FAST = 12;
export const MACD_SLOW = 26;
export const MACD_SIGNAL = 9;
export const BOLLINGER_PERIOD = 20;
export const BOLLINGER_MULT = 2;

/** Wilder-smoothed RSI. Null until `period` changes have been seen. */
export function rsi(values: number[], period = RSI_PERIOD): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length <= period) return out;

  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i <= period; i += 1) {
    const change = values[i] - values[i - 1];
    if (change >= 0) gainSum += change;
    else lossSum -= change;
  }
  let avgGain = gainSum / period;
  let avgLoss = lossSum / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  for (let i = period + 1; i < values.length; i += 1) {
    const change = values[i] - values[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(change, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-change, 0)) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

/** Exponential moving average, seeded with the SMA of the first `period` values. */
export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period) return out;

  let sum = 0;
  for (let i = 0; i < period; i += 1) sum += values[i];
  let current = sum / period;
  out[period - 1] = current;

  const k = 2 / (period + 1);
  for (let i = period; i < values.length; i += 1) {
    current = values[i] * k + current * (1 - k);
    out[i] = current;
  }
  return out;
}

export interface MacdResult {
  /** MACD line: fast EMA minus slow EMA. */
  line: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
}

export function macd(
  values: number[],
  fast = MACD_FAST,
  slow = MACD_SLOW,
  signalPeriod = MACD_SIGNAL,
): MacdResult {
  const length = values.length;
  const line: (number | null)[] = new Array(length).fill(null);
  const signal: (number | null)[] = new Array(length).fill(null);
  const histogram: (number | null)[] = new Array(length).fill(null);

  const fastEma = ema(values, fast);
  const slowEma = ema(values, slow);
  for (let i = 0; i < length; i += 1) {
    if (fastEma[i] !== null && slowEma[i] !== null) {
      line[i] = (fastEma[i] as number) - (slowEma[i] as number);
    }
  }

  // The signal line is an EMA of the MACD line over its defined tail.
  const defined = line.filter((value): value is number => value !== null);
  const signalTail = ema(defined, signalPeriod);
  const offset = length - defined.length;
  for (let i = 0; i < length; i += 1) {
    const tailIndex = i - offset;
    if (tailIndex >= 0 && signalTail[tailIndex] !== null && line[i] !== null) {
      signal[i] = signalTail[tailIndex];
      histogram[i] = (line[i] as number) - (signal[i] as number);
    }
  }
  return { line, signal, histogram };
}

export interface BollingerBand {
  mid: number | null;
  upper: number | null;
  lower: number | null;
}

/** SMA ± `mult` population standard deviations. */
export function bollinger(
  values: number[],
  period = BOLLINGER_PERIOD,
  mult = BOLLINGER_MULT,
): BollingerBand[] {
  const out: BollingerBand[] = values.map(() => ({ mid: null, upper: null, lower: null }));
  for (let i = period - 1; i < values.length; i += 1) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j += 1) sum += values[j];
    const mid = sum / period;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j += 1) variance += (values[j] - mid) ** 2;
    const deviation = Math.sqrt(variance / period);
    out[i] = { mid, upper: mid + mult * deviation, lower: mid - mult * deviation };
  }
  return out;
}

/**
 * Cumulative average price standing in for VWAP. The feed carries no volume,
 * so every tick is weighted equally — disclosed on the panel that shows it.
 */
export function vwap(values: number[]): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    out[i] = sum / (i + 1);
  }
  return out;
}

/** The last defined value of a null-padded series, for the live chips. */
export function lastValue(series: (number | null)[]): number | null {
  for (let i = series.length - 1; i >= 0; i -= 1) {
    if (series[i] !== null) return series[i];
  }
  return null;
}
