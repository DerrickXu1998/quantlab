import type { Instrument } from '../../../src/api/client';
import type { RawCatalogModel, SignalCategory, StrategyRole } from '../../../src/api/types';

function rule(
  name: string,
  category: SignalCategory,
  summary: string,
  extra: Partial<RawCatalogModel> = {},
): RawCatalogModel {
  return {
    name,
    version: '1.0.0',
    category,
    summary,
    direction_semantics: `bullish when ${name} fires`,
    roles: ['entry', 'exit'] as StrategyRole[],
    lookback_days: 20,
    scale_class: 'scale_free',
    requires_facts: [],
    parameters: [
      { name: 'period', type: 'int', default: 20, minimum: 2, maximum: 200, choices: null },
    ],
    ...extra,
  };
}

/**
 * The registry as the warehouse actually holds it: twenty-two rules, of which
 * exactly three were ever materialised into the signals table.
 *
 * That three-of-twenty-two split is the whole reason this mode exists. The
 * panel it replaces rendered signal *output*, so it advertised the three and
 * was silent about the nineteen — including all nine that read filed accounts
 * (docs/RESEARCH.md §1b). A fixture with history on every rule would let a
 * regression back in unnoticed.
 */
export const MATERIALISED = ['breakout-20d', 'rsi-threshold', 'sma-crossover'];

export const CATALOGUE: RawCatalogModel[] = [
  // The three builtins, the only ones with signals on disk.
  rule('sma-crossover', 'trend', 'Fast moving average crossing the slow one.'),
  rule('rsi-threshold', 'momentum', 'RSI crossing out of its oversold band.'),
  rule('breakout-20d', 'volatility', 'Close above the highest high of the prior 20 bars.'),

  // The technical library: registered, runnable, never materialised.
  rule('macd-crossover', 'momentum', 'MACD line crossing its signal line.'),
  rule('adx-trend-filter', 'trend', 'Trend strength above a floor.', {
    roles: ['filter'] as StrategyRole[],
  }),
  rule('donchian-breakout', 'volatility', 'Close outside the Donchian channel.'),
  rule('bollinger-reversion', 'mean_reversion', 'Close returning inside the bands.'),
  rule('atr-stop', 'volatility', 'A stop set a multiple of ATR below entry.'),
  rule('volume-surge', 'volume', 'Volume above its own rolling average.'),
  rule('obv-trend', 'volume', 'On-balance volume making a new extreme.'),
  rule('stochastic-cross', 'momentum', '%K crossing %D inside the oversold band.'),
  rule('ema-ribbon', 'trend', 'A fanned set of EMAs in order.'),
  rule('keltner-squeeze', 'volatility', 'Bollinger bands inside the Keltner channel.'),

  // The nine that read filed accounts. Every one of them was invisible.
  rule('pe-filter', 'fundamental', 'Price/earnings below a ceiling.', {
    requires_facts: ['net_income', 'shares_outstanding'],
    roles: ['filter'] as StrategyRole[],
  }),
  rule('pb-filter', 'fundamental', 'Price/book below a ceiling.', {
    requires_facts: ['equity', 'shares_outstanding'],
    roles: ['filter'] as StrategyRole[],
  }),
  rule('roe-floor', 'fundamental', 'Return on equity above a floor.', {
    requires_facts: ['net_income', 'equity'],
    roles: ['filter'] as StrategyRole[],
  }),
  rule('leverage-ceiling', 'fundamental', 'Liabilities to assets below a ceiling.', {
    requires_facts: ['total_liabilities', 'total_assets'],
    roles: ['filter'] as StrategyRole[],
  }),
  rule('net-margin-floor', 'fundamental', 'Net margin above a floor.', {
    requires_facts: ['net_income', 'revenue'],
    roles: ['filter'] as StrategyRole[],
  }),
  rule('gross-margin-floor', 'fundamental', 'Gross margin above a floor.', {
    requires_facts: ['gross_profit', 'revenue'],
    roles: ['filter'] as StrategyRole[],
  }),
  rule('current-ratio-floor', 'fundamental', 'Current ratio above a floor.', {
    requires_facts: ['current_assets', 'current_liabilities'],
    roles: ['filter'] as StrategyRole[],
  }),
  rule('revenue-growth', 'fundamental', 'Revenue growing year on year.', {
    requires_facts: ['revenue'],
  }),
  rule('cash-conversion', 'fundamental', 'Operating cash flow covering net income.', {
    requires_facts: ['operating_cash_flow', 'net_income'],
  }),
];

/**
 * A rule as a backend that predates §2 sends it: no `category`, no `roles`,
 * no `requires_facts`, no `summary`.
 *
 * `model?.requires_facts.length` crashed this app once — the optional chain
 * guards the model and then dereferences a field that is not there. This entry
 * is what keeps that from coming back.
 */
export const LEGACY_RULE = {
  name: 'legacy-rule',
  version: '0.9.0',
  direction_semantics: 'bullish when the legacy rule fires',
  lookback_days: 10,
  scale_class: 'scale_free',
  parameters: [],
} as unknown as RawCatalogModel;

export const INSTRUMENTS = [
  { symbol: 'CAT.US', name: 'Caterpillar Inc', currency: 'USD' },
  { symbol: 'DE.US', name: 'Deere & Company', currency: 'USD' },
] as unknown as Instrument[];
