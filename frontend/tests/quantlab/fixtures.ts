import type { Model, Run, RunDetail, RunPerformance } from '../../src/api/client';

export const model: Model = {
  name: 'sma-crossover',
  version: '1.0.0',
  lookback_days: 50,
  scale_class: 'price_scaled',
  direction_semantics: 'bullish when fast crosses above slow',
  parameters: [
    {
      name: 'fast',
      type: 'int',
      default: 20,
      minimum: 2,
      maximum: 100,
      choices: null,
      description: 'Fast window.',
    },
  ],
};

export function makeRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 'run-1',
    name: null,
    model_name: 'sma-crossover',
    model_version: '1.0.0',
    parameters: { fast: 20 },
    symbols: ['ZZTRND'],
    start_date: '2024-01-01',
    end_date: '2024-12-31',
    status: 'completed',
    error: null,
    created_at: '2026-09-19T12:00:00Z',
    signal_count: 2,
    coverage: {
      instruments_requested: 1,
      instruments_with_data: 1,
      instruments_full_warmup: 1,
    },
    model_available: true,
    dataset: 'sqlite',
    instrument_ids: null,
    ingest_run_ids: null,
    corporate_actions: [],
    re_runnable: true,
    signals: [],
    ...overrides,
  };
}

export function makePerformance(overrides: Partial<RunPerformance> = {}): RunPerformance {
  return {
    run_id: 'run-1',
    initial_capital: 100_000,
    equity: [
      { date: '2024-01-01', value: 100_000 },
      { date: '2024-01-02', value: 108_000 },
      { date: '2024-01-03', value: 112_000 },
    ],
    benchmark: [
      { date: '2024-01-01', value: 100_000 },
      { date: '2024-01-02', value: 101_000 },
      { date: '2024-01-03', value: 103_000 },
    ],
    metrics: {
      total_return: 0.12,
      sharpe_ratio: 1.84,
      max_drawdown: -0.07,
      win_rate: 0.6,
      trade_count: 5,
      winning_trades: 3,
      losing_trades: 2,
    },
    trades: [
      {
        symbol: 'ZZTRND',
        entry_date: '2024-01-01',
        entry_price: 100,
        exit_date: '2024-01-03',
        exit_price: 112,
        return_pct: 0.12,
        open: false,
      },
      {
        symbol: 'ZZMEAN',
        entry_date: '2024-01-02',
        entry_price: 50,
        exit_date: null,
        exit_price: 54,
        return_pct: 0.08,
        open: true,
      },
    ],
    assumptions: ['Long-only.', 'No transaction costs and no slippage are charged.'],
    ...overrides,
  };
}

export const runSummary: Run = makeRun();
