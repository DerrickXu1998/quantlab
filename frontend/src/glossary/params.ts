import type { UnitKind } from './units';

/**
 * The unit of every signal-rule parameter.
 *
 * The explanation of a parameter is the rule's own description, from the
 * backend registry -- it is specific (the same `period` is RSI's in one rule
 * and ADX's in another). What the registry does not carry is a unit in a form
 * the UI can reason about, so it lives here: by `rule.param` where a name
 * means different things in different rules, by bare name where it does not.
 *
 * A parameter missing from both tables shows its description with no unit
 * line; backend/tests/unit/test_glossary_coverage.py checks that every
 * registered parameter is covered.
 */
const BY_RULE_PARAM: Record<string, UnitKind> = {
  'roc-momentum.upper': 'percent-of-price',
  'roc-momentum.lower': 'percent-of-price',
  'adx-trend-filter.threshold': 'level-0-100',
  'zscore-reversion.threshold': 'std-devs',
  'accrual-reversal.threshold': 'fraction',
  'revenue-growth.threshold': 'fraction',
  // The HY spread is a daily series whatever the run's bars.
  'macro-risk-off.hy_window': 'trading-days',
};

const BY_NAME: Record<string, UnitKind> = {
  // Indicator windows: bars of the run's bar size.
  period: 'bars',
  fast: 'bars',
  slow: 'bars',
  signal: 'bars',
  window: 'bars',
  k_period: 'bars',
  d_period: 'bars',
  entry_window: 'bars',
  exit_window: 'bars',
  // Oscillator levels.
  overbought: 'level-0-100',
  oversold: 'level-0-100',
  floor: 'level-0-100',
  ceiling: 'level-0-100',
  // Thresholds and multiples.
  num_std: 'std-devs',
  multiple: 'multiple',
  hy_widen: 'percentage-points',
  vix_max: 'index-level',
  // Fundamentals.
  max_pe: 'ratio',
  min_pe: 'ratio',
  max_pb: 'ratio',
  min_pb: 'ratio',
  max_ratio: 'ratio',
  min_ratio: 'ratio',
  min_margin: 'fraction',
  min_roe: 'fraction',
  periods: 'count',
  max_stale_days: 'calendar-days',
  // Switches.
  use_d: 'on-off',
  use_hy_spread: 'on-off',
  require_sign: 'on-off',
};

export function paramUnit(rule: string, param: string): UnitKind | undefined {
  return BY_RULE_PARAM[`${rule}.${param}`] ?? BY_NAME[param];
}

/** Every parameter name the tables know, for the coverage test. */
export const KNOWN_PARAMS = { byRuleParam: BY_RULE_PARAM, byName: BY_NAME };
