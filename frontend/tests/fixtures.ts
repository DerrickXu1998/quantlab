import type { Instrument, PriceBar, Signal } from '../src/api/client';

export function makeSignal(overrides: Partial<Signal> = {}): Signal {
  return {
    id: 1,
    symbol: 'ZZTRND',
    date: '2024-03-15',
    rule_name: 'sma-crossover',
    rule_version: '1.0.0',
    parameters: { fast: 20, slow: 50 },
    direction: 'bullish',
    trigger_values: { sma_fast: 101.2, sma_slow: 99.8 },
    data_window_end: '2024-03-15',
    ...overrides,
  };
}

export function makeInstrument(overrides: Partial<Instrument> = {}): Instrument {
  return {
    symbol: 'ZZTRND',
    name: 'Zeno Trend Industries (synthetic)',
    currency: 'USD',
    kind: 'equity',
    regime_profile: 'trending',
    ...overrides,
  };
}

/** A warehouse macro pseudo-instrument: daily value series, never a price. */
export function makeMacroInstrument(overrides: Partial<Instrument> = {}): Instrument {
  return {
    symbol: 'UST10Y.FRED',
    name: '10-Year Treasury constant maturity yield',
    currency: 'USD',
    kind: 'macro',
    regime_profile: 'mixed',
    ...overrides,
  };
}

export function makeBar(overrides: Partial<PriceBar> = {}): PriceBar {
  return {
    symbol: 'ZZTRND',
    date: '2024-03-14',
    open: 100,
    high: 103,
    low: 99,
    close: 101,
    volume: 1000000,
    ...overrides,
  };
}
