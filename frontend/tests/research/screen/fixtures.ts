import type { ScreenMetricCoverage, ScreenResult, ScreenRow } from '../../../src/api/types';

/**
 * Coverage as the warehouse actually reports it: uneven, and by more than two
 * to one. These are the measured figures from docs/RESEARCH.md §2 — gross
 * profit filed by 237 instruments, revenue by 376, net income by 468 — because
 * a fixture with uniform coverage would make every coverage assertion here
 * pass for the wrong reason.
 */
export const COVERAGE: ScreenMetricCoverage[] = [
  { metric: 'pe', measured: 425, universe: 598, requires: ['net_income', 'shares_outstanding'] },
  { metric: 'pb', measured: 425, universe: 598, requires: ['equity', 'shares_outstanding'] },
  { metric: 'roe', measured: 437, universe: 598, requires: ['net_income', 'equity'] },
  { metric: 'leverage', measured: 423, universe: 598, requires: ['total_liabilities', 'total_assets'] },
  { metric: 'net_margin', measured: 376, universe: 598, requires: ['net_income', 'revenue'] },
  { metric: 'gross_margin', measured: 237, universe: 598, requires: ['gross_profit', 'revenue'] },
  {
    metric: 'current_ratio',
    measured: 372,
    universe: 598,
    requires: ['current_assets', 'current_liabilities'],
  },
];

export const ROWS: ScreenRow[] = [
  {
    symbol: 'CAT.US',
    name: 'Caterpillar Inc',
    values: {
      pe: 11.6438,
      pb: 6.2071,
      roe: 0.41237,
      leverage: 0.7891,
      net_margin: 0.15871,
      // Never filed gross profit. This must render as a dash, never as 0.
      gross_margin: null,
      current_ratio: 1.3842,
    },
  },
  {
    symbol: 'DE.US',
    name: 'Deere & Company',
    values: {
      pe: 9.8123,
      pb: 4.1002,
      roe: 0.3311,
      leverage: 0.8204,
      net_margin: 0.1402,
      gross_margin: 0.3117,
      current_ratio: 2.0451,
    },
  },
];

export function makeScreenResult(overrides: Partial<ScreenResult> = {}): ScreenResult {
  return {
    as_of: '2026-09-18',
    universe: 'liquid-500-ftse-core',
    universe_size: 598,
    rows: ROWS,
    coverage: COVERAGE,
    sort_by: 'roe',
    excluded_by_constraint: 312,
    excluded_unmeasured: 284,
    ...overrides,
  };
}

export const UNIVERSES = {
  items: [{ name: 'liquid-500-ftse-core', as_of: '2026-09-18', size: 598 }],
};
