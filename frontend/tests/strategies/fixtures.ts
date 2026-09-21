import type { CatalogModel, ExecutionConfig, StrategyTemplate } from '../../src/api/types';
import { DEFAULT_EXECUTION } from '../../src/api/types';

/**
 * A miniature registry with the shape §2 describes: a rule that can enter and
 * exit, another that can, and one that honestly advertises `["filter"]` only.
 * The third is the whole point — it is what role enforcement is tested against.
 */

export const rsiThreshold: CatalogModel = {
  name: 'rsi-threshold',
  version: '1.0.0',
  category: 'mean_reversion',
  summary: 'RSI crossing out of its oversold band.',
  direction_semantics: 'bullish when RSI crosses back above the oversold level',
  roles: ['entry', 'exit'],
  lookback_days: 14,
  scale_class: 'scale_free',
  requires_facts: [],
  parameters: [
    {
      name: 'period',
      type: 'int',
      default: 14,
      minimum: 2,
      maximum: 100,
      choices: null,
      description: 'Bars of history.',
    },
    {
      name: 'oversold',
      type: 'int',
      default: 30,
      minimum: 1,
      maximum: 50,
      choices: null,
      description: 'Level that counts as oversold.',
    },
  ],
};

export const macdCrossover: CatalogModel = {
  name: 'macd-crossover',
  version: '1.0.0',
  category: 'momentum',
  summary: 'MACD line crossing its signal line.',
  direction_semantics: 'bullish when the MACD line crosses above its signal',
  roles: ['entry', 'exit'],
  lookback_days: 35,
  scale_class: 'scale_free',
  requires_facts: [],
  parameters: [
    { name: 'fast', type: 'int', default: 12, minimum: 2, maximum: 100, choices: null },
    { name: 'slow', type: 'int', default: 26, minimum: 3, maximum: 200, choices: null },
  ],
};

export const adxFilter: CatalogModel = {
  name: 'adx-trend-filter',
  version: '1.0.0',
  category: 'trend',
  summary: 'ADX above its threshold, meaning the market is trending.',
  direction_semantics: 'bullish state while ADX is above the threshold',
  roles: ['filter'],
  lookback_days: 28,
  scale_class: 'scale_free',
  requires_facts: [],
  parameters: [
    { name: 'period', type: 'int', default: 14, minimum: 2, maximum: 100, choices: null },
    { name: 'threshold', type: 'int', default: 25, minimum: 1, maximum: 100, choices: null },
  ],
};

export const catalog: CatalogModel[] = [rsiThreshold, macdCrossover, adxFilter];

/**
 * `GET /strategy-templates` as the server really answers it: ids, order and
 * component parameters copied from a live response, so a change to the real
 * catalogue shows up here as a failing test rather than as a surprise in the
 * browser.
 */
function execution(overrides: Partial<ExecutionConfig>): ExecutionConfig {
  return { ...DEFAULT_EXECUTION, commission_bps: 5, slippage_bps: 2, ...overrides };
}

export const templates: StrategyTemplate[] = [
  {
    id: 'rsi-mean-reversion',
    name: 'RSI mean reversion',
    description: 'Buy a name that has been sold off and is starting to recover.',
    components: [
      {
        rule_name: 'rsi-threshold',
        rule_version: undefined,
        parameters: { period: 14, oversold: 30.0, overbought: 70.0 },
        role: 'entry',
        weight: 1,
        invert: false,
      },
      {
        rule_name: 'rsi-threshold',
        rule_version: undefined,
        parameters: { period: 14, oversold: 30.0, overbought: 70.0 },
        role: 'exit',
        weight: 1,
        invert: false,
      },
    ],
    entry_logic: 'any',
    exit_logic: 'any',
    entry_threshold: 1,
    exit_threshold: 1,
    combine_window_days: 1,
    execution: execution({ stop_loss_pct: 0.08, take_profit_pct: 0.15, max_holding_days: 60 }),
  },
  {
    id: 'macd-trend-following',
    name: 'MACD trend following',
    description: 'Follow momentum, with an ADX filter doing the real work.',
    components: [
      {
        rule_name: 'macd-crossover',
        parameters: { fast: 12, slow: 26, signal: 9 },
        role: 'entry',
        weight: 1,
        invert: false,
      },
      {
        rule_name: 'adx-trend-filter',
        parameters: { period: 14, threshold: 25.0 },
        role: 'filter',
        weight: 1,
        invert: false,
      },
    ],
    entry_logic: 'any',
    exit_logic: 'any',
    entry_threshold: 1,
    exit_threshold: 1,
    combine_window_days: 1,
    execution: execution({ trailing_stop_pct: 0.12, min_holding_days: 3 }),
  },
  {
    id: 'donchian-breakout',
    name: 'Donchian breakout with trend and volume filters',
    description: 'The classic turtle shape, with two filters dropping the weakest breaks.',
    components: [
      {
        rule_name: 'donchian-breakout',
        parameters: { entry_window: 20, exit_window: 10 },
        role: 'entry',
        weight: 1,
        invert: false,
      },
      {
        rule_name: 'volume-spike',
        parameters: { window: 20, multiple: 1.3 },
        role: 'filter',
        weight: 1,
        invert: false,
      },
    ],
    entry_logic: 'any',
    exit_logic: 'any',
    entry_threshold: 1,
    exit_threshold: 1,
    combine_window_days: 1,
    execution: execution({ atr_stop_multiple: 2.5, atr_period: 14, max_positions: 5 }),
  },
  {
    id: 'dual-confirmation',
    name: 'Dual-confirmation reversion',
    description: 'Requires two independent things to agree before entering.',
    components: [
      {
        rule_name: 'rsi-threshold',
        parameters: { period: 14, oversold: 35.0, overbought: 70.0 },
        role: 'entry',
        weight: 1,
        invert: false,
      },
    ],
    entry_logic: 'all',
    exit_logic: 'any',
    entry_threshold: 1,
    exit_threshold: 1,
    combine_window_days: 3,
    execution: execution({ stop_loss_pct: 0.06, max_holding_days: 30 }),
  },
];
