import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import type { RunDetailV2, RunPerformanceV2 } from '../../src/api/types';
import { DEFAULT_EXECUTION } from '../../src/api/types';
import { RunResultsView } from '../../src/components/RunResultsView';
import { RunsProvider } from '../../src/runs/RunsContext';
import { installCanvas2d } from '../mocks/canvas-2d';
import { installResizeObserver } from '../mocks/resize-observer';
import { makePerformance, makeRun } from './fixtures';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listModels: vi.fn(),
    listRuns: vi.fn(),
    getRunPerformance: vi.fn(),
  };
});

installResizeObserver();
installCanvas2d();

/** A §5 performance payload: per-trade detail, costs, exit-reason counts. */
function performanceV2(): RunPerformanceV2 {
  return {
    ...makePerformance(),
    trades: [
      {
        symbol: 'ZZTRND',
        side: 'long',
        entry_date: '2024-01-01',
        entry_price: 101.2,
        exit_date: '2024-01-09',
        exit_price: 108,
        qty: 96.2,
        return_pct: 0.0672,
        open: false,
        exit_reason: 'take_profit',
        pnl: 654.16,
        fees: 12.4,
      },
      {
        symbol: 'ZZMEAN',
        side: 'short',
        entry_date: '2024-02-01',
        entry_price: 50,
        exit_date: '2024-02-05',
        exit_price: 54,
        qty: 40,
        return_pct: -0.08,
        open: false,
        exit_reason: 'stop_loss',
        pnl: -160,
        fees: 4.2,
      },
    ],
    costs: { commission: 118.44, slippage: 96.1 },
    exit_reasons: { take_profit: 1, stop_loss: 1 },
    assumptions: [
      '0.05% commission and 0.02% slippage are charged per side.',
      'Entries and exits fill at the next bar’s open.',
    ],
  };
}

function runWithStrategy(): RunDetailV2 {
  return {
    ...makeRun(),
    strategy: {
      name: 'RSI oversold in an uptrend',
      components: [
        { rule_name: 'rsi-threshold', parameters: { period: 14, oversold: 30 }, role: 'entry' },
        {
          rule_name: 'adx-trend-filter',
          parameters: { period: 14, threshold: 25 },
          role: 'filter',
        },
      ],
      entry_logic: 'all',
      exit_logic: 'any',
      combine_window_days: 2,
    },
    execution: {
      ...DEFAULT_EXECUTION,
      commission_bps: 5,
      slippage_bps: 2,
      stop_loss_pct: 0.05,
      fill_timing: 'next_open',
      max_positions: 4,
    },
    // The engine's real shape, counters and all — copied from a live
    // /runs/{id} response, not from the contract's shorter example.
    execution_summary: {
      orders: 42,
      fills: 40,
      rejected_no_cash: 1,
      rejected_max_positions: 3,
      rejected_cooldown: 0,
      rejected_shorts_disabled: 10,
      dropped_no_bar: 1,
      contradictions: 0,
      total_commission: 118.44,
      total_slippage: 96.1,
    },
  };
}

function renderResults(run: RunDetailV2) {
  return render(
    <RunsProvider>
      <RunResultsView run={run} />
    </RunsProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listModels).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.getRunPerformance).mockResolvedValue(performanceV2());
});

describe('run results, with execution criteria', () => {
  it('shows side, quantity, exit reason, P&L and fees on every trade', async () => {
    renderResults(runWithStrategy());

    const log = await screen.findByTestId('trade-log');
    const [, first, second] = within(log).getAllByRole('row');

    expect(within(first).getByText('long')).toBeInTheDocument();
    expect(within(first).getByText('96.20')).toBeInTheDocument();
    expect(within(first).getByText('Take profit')).toBeInTheDocument();
    expect(within(first).getByText('+654.16')).toBeInTheDocument();
    expect(within(first).getByText('12.40')).toBeInTheDocument();

    expect(within(second).getByText('short')).toBeInTheDocument();
    expect(within(second).getByText('Stop loss')).toBeInTheDocument();
    // Red is reserved for losses, and this is one.
    expect(within(second).getByText('-160.00')).toHaveClass('text-destructive');
  });

  it('breaks the exits down by reason and totals what trading cost', async () => {
    renderResults(runWithStrategy());

    const breakdown = await screen.findByTestId('exit-breakdown');
    expect(within(breakdown).getByText('Take profit')).toBeInTheDocument();
    expect(within(breakdown).getByText('Stop loss')).toBeInTheDocument();

    const costs = within(breakdown).getByTestId('run-costs');
    expect(costs).toHaveTextContent('$118');
    expect(costs).toHaveTextContent('$96');

    // Orders that could not be afforded and signals with no bar to fill on
    // both changed the result, so both are stated.
    const summary = within(breakdown).getByTestId('execution-summary');
    expect(summary).toHaveTextContent('42');
    expect(summary).toHaveTextContent('40');
  });

  it('surfaces the rejections that mean the strategy was not really tested', async () => {
    renderResults(runWithStrategy());

    const summary = await screen.findByTestId('execution-summary');

    // Ten bearish entries were discarded because shorts are switched off, and
    // three more hit the position cap — on the fill count alone this run is
    // indistinguishable from a strategy that simply signalled rarely.
    const shorts = within(summary).getByTitle(/allow shorts is switched off/i);
    expect(shorts).toHaveTextContent(/shorts off/i);
    expect(shorts).toHaveClass('text-destructive');
    expect(summary).toHaveTextContent('10');

    expect(within(summary).getByTitle(/max positions was already reached/i)).toHaveClass(
      'text-destructive',
    );
    // A counter at zero is reported, but not dressed up as a problem.
    expect(within(summary).getByTitle(/closed too recently/i)).not.toHaveClass('text-destructive');
  });

  it('shows only the counters a backend at the documented shape reports', async () => {
    const run = runWithStrategy();
    renderResults({
      ...run,
      execution_summary: {
        orders: 42,
        fills: 40,
        rejected_no_cash: 1,
        dropped_no_bar: 1,
        total_commission: 118.44,
        total_slippage: 96.1,
      },
    });

    const summary = await screen.findByTestId('execution-summary');
    expect(summary).toHaveTextContent(/orders/i);
    // Absent is absent: no blank rows for counters this engine did not send.
    expect(within(summary).queryByTitle(/allow shorts is switched off/i)).toBeNull();
    expect(within(summary).queryByTitle(/max positions was already reached/i)).toBeNull();
  });

  it('renders the derived assumptions prominently rather than folded away', async () => {
    renderResults(runWithStrategy());

    const assumptions = await screen.findByTestId('performance-assumptions');
    expect(assumptions).toHaveTextContent(/0\.05% commission/);
    expect(assumptions).toHaveTextContent(/next bar/);
    // Open by default: this is information about the run, not a disclaimer.
    expect(assumptions.querySelector('details')).toBeNull();
  });

  it('reports the strategy and execution the run actually used', async () => {
    renderResults(runWithStrategy());

    const provenance = await screen.findByTestId('run-strategy');
    expect(provenance).toHaveTextContent('RSI oversold in an uptrend');
    expect(provenance).toHaveTextContent('rsi-threshold');
    expect(provenance).toHaveTextContent('adx-trend-filter');
    expect(provenance).toHaveTextContent('period=14, threshold=25');

    expect(within(provenance).getByTestId('run-execution')).toHaveTextContent(
      /fills next open.*5 bps commission.*5% stop/,
    );
  });

  it('stays readable for a run recorded before execution criteria existed', async () => {
    vi.mocked(apiClient.getRunPerformance).mockResolvedValue({
      ...makePerformance(),
      trades: makePerformance().trades,
    });

    renderResults(makeRun());

    // No strategy, no costs, no exit reasons — and no invented ones either.
    expect(await screen.findByTestId('trade-log')).toBeInTheDocument();
    expect(screen.queryByTestId('run-strategy')).not.toBeInTheDocument();
    expect(screen.queryByTestId('exit-breakdown')).not.toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});
