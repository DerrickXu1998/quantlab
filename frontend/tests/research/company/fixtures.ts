import type { CompanyOverview, FundamentalFact } from '../../../src/api/types';

export function makeFact(overrides: Partial<FundamentalFact> = {}): FundamentalFact {
  return {
    concept: 'revenue',
    value: 67_060_000_000,
    period_start: '2023-01-01',
    period_end: '2023-12-31',
    filed_at: '2024-02-14',
    days_stale: 120,
    unit: 'USD',
    ...overrides,
  };
}

export function makeOverview(overrides: Partial<CompanyOverview> = {}): CompanyOverview {
  return {
    symbol: 'CAT',
    name: 'Caterpillar Inc.',
    exchange: 'NYSE',
    currency: 'USD',
    sector: '',
    as_of: '2024-06-30',
    first_bar: '2010-01-04',
    last_bar: '2024-06-28',
    last_close: 17.68000030517578,
    facts: [makeFact()],
    concepts_available: ['revenue', 'net_income'],
    concepts_missing: ['gross_profit'],
    signals: [
      { rule_name: 'breakout-20d', count: 412, last_date: '2024-06-21', last_direction: 'bullish' },
      { rule_name: 'rsi-threshold', count: 98, last_date: '2024-05-02', last_direction: 'bearish' },
    ],
    signal_total: 510,
    ...overrides,
  };
}
