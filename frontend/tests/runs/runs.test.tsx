import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import type { RunDetail } from '../../src/api/client';
import { DEFAULT_EXECUTION } from '../../src/api/types';
import { TabBar } from '../../src/components/ui/tabs';
import { RunNotices } from '../../src/runs/RunNotices';
import { ACTIVE_POLL_MS, RunsProvider, useRuns } from '../../src/runs/RunsContext';
import { RunsView } from '../../src/runs/RunsView';
import { executionSummary } from '../../src/strategies/executionSummary';
import { makePerformance, makeRun } from '../quantlab/fixtures';
import { PENDING_RETRY_MS } from '../../src/quantlab/data/useRunPerformance';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listModels: vi.fn(),
    listRuns: vi.fn(),
    getRun: vi.fn(),
    cancelRun: vi.fn(),
    deleteRun: vi.fn(),
    createStrategyRun: vi.fn(),
    getRunPerformance: vi.fn(),
  };
});

const strategy = {
  name: 'Momentum v3',
  description: '',
  components: [{ rule_name: 'sma-crossover', role: 'entry', parameters: {}, weight: 1, invert: false }],
  entry_logic: 'all',
  exit_logic: 'any',
  entry_threshold: 1,
  exit_threshold: 1,
  combine_window_days: 1,
  execution: { ...DEFAULT_EXECUTION, bar_frequency: '5m' },
};

function run(overrides: Partial<RunDetail> & Record<string, unknown>): RunDetail {
  return makeRun({ strategy, ...overrides } as Partial<RunDetail>);
}

const queued = run({
  id: 'q1',
  status: 'queued',
  queue_position: 2,
  estimated_bars: 2_000_000,
  signal_count: 0,
  signals: [],
} as never);
const failed = run({
  id: 'f1',
  status: 'failed',
  error: 'none of the 3 selected instruments has any filing for Revenues',
  error_category: 'data',
} as never);
const done = run({
  id: 'c1',
  status: 'completed',
  metrics: {
    total_return: 0.841,
    sharpe_ratio: 0.71,
    max_drawdown: -0.22,
    win_rate: 0.5,
    trade_count: 1204,
    winning_trades: 600,
    losing_trades: 604,
  },
  summary: {
    benchmark_return: 0.51,
    excess_return: 0.331,
    alpha: 0.02,
    beta: 0.9,
    information_ratio: 0.4,
    equity_spark: [1, 1.2, 1.5, 1.84],
    benchmark_spark: [1, 1.1, 1.3, 1.51],
  },
} as never);
// Recorded before results were stored: the worker is still computing them.
const older = run({ id: 'o1', status: 'completed', metrics: null, summary: null } as never);

function renderRuns(runId: string | null = null) {
  const onOpen = vi.fn();
  const onClone = vi.fn();
  render(
    <RunsProvider>
      <RunsView runId={runId} onOpen={onOpen} onBack={vi.fn()} onClone={onClone} />
      <RunNotices />
    </RunsProvider>,
  );
  return { onOpen, onClone };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listModels).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 3, items: [queued, failed, done] } as never);
  vi.mocked(apiClient.getRun).mockImplementation(async (id: string) =>
    [queued, failed, done].find((r) => r.id === id) as never,
  );
});

afterEach(() => {
  vi.useRealTimers();
});

describe('Runs table', () => {
  it('shows every run with its status in words, and the headline numbers of finished ones', async () => {
    renderRuns();
    const table = await screen.findByTestId('runs-table');

    const queuedRow = within(table).getByTestId('run-row-q1');
    expect(within(queuedRow).getByTestId('run-status')).toHaveTextContent('Queued #2');
    // Not yet run: an expected duration, never a fake figure. 2M bars, one
    // component: read 10 s + signals 36 s + backtest 12 s.
    expect(queuedRow).toHaveTextContent('~58 s');

    const failedRow = within(table).getByTestId('run-row-f1');
    expect(within(failedRow).getByTestId('run-status')).toHaveTextContent('Failed');
    expect(failedRow).toHaveTextContent('Data · none of the 3 selected instruments');

    const doneRow = within(table).getByTestId('run-row-c1');
    expect(doneRow).toHaveTextContent('+84.10%');
    expect(doneRow).toHaveTextContent('0.71');
    expect(doneRow).toHaveTextContent('1,204');
  });

  it('filters by status', async () => {
    const user = userEvent.setup();
    renderRuns();
    await screen.findByTestId('runs-table');

    await user.selectOptions(screen.getByLabelText('Status'), 'active');

    expect(screen.getByTestId('run-row-q1')).toBeInTheDocument();
    expect(screen.queryByTestId('run-row-c1')).not.toBeInTheDocument();
  });

  it('cancels a queued run on the server', async () => {
    vi.mocked(apiClient.cancelRun).mockResolvedValue({ ...queued, status: 'cancelled' } as never);
    const user = userEvent.setup();
    renderRuns();
    await screen.findByTestId('runs-table');

    await user.click(screen.getByRole('button', { name: /cancel momentum v3/i, hidden: false }));

    expect(apiClient.cancelRun).toHaveBeenCalledWith('q1');
    await waitFor(() =>
      expect(within(screen.getByTestId('run-row-q1')).getByTestId('run-status')).toHaveTextContent('Cancelled'),
    );
  });

  it('clones a run back into the editor with its recorded configuration', async () => {
    const user = userEvent.setup();
    const { onClone } = renderRuns();
    await screen.findByTestId('runs-table');

    const row = screen.getByTestId('run-row-c1');
    await user.click(within(row).getByRole('button', { name: /clone .* to the editor/i }));

    expect(onClone).toHaveBeenCalledWith(expect.objectContaining({ run: expect.objectContaining({ id: 'c1' }) }));
  });

  it('says what to do when there are no runs', async () => {
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
    renderRuns();
    expect(await screen.findByTestId('runs-empty')).toHaveTextContent(/submit/i);
  });
});

describe('Run history against the benchmark', () => {
  it('shows each run against buy-and-hold, with a small chart of both', async () => {
    renderRuns();
    const row = await screen.findByTestId('run-row-c1');

    expect(row).toHaveTextContent('+51.00%'); // buy-and-hold of the same tickers
    expect(row).toHaveTextContent('+33.10%'); // the strategy's excess over it
    expect(within(row).getByTestId('run-sparkline')).toHaveAccessibleName(
      /strategy ends at 1\.84x, buy-and-hold at 1\.51x/,
    );
  });

  it('summarises the runs shown from their stored figures', async () => {
    renderRuns();
    const aggregate = await screen.findByTestId('runs-aggregate');

    expect(aggregate).toHaveTextContent(/With results\s*1/);
    expect(aggregate).toHaveTextContent(/Beat buy & hold\s*1 of 1/);
    expect(aggregate).toHaveTextContent('+84.10%');
  });

  it('says an older run is preparing its results rather than showing blanks', async () => {
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 2, items: [older, done] } as never);
    renderRuns();
    const row = await screen.findByTestId('run-row-o1');

    expect(within(row).getByTestId('run-preparing')).toHaveTextContent(/preparing results/);
    expect(screen.getByTestId('runs-aggregate')).toHaveTextContent('+1 preparing');
  });

  it('waits for an older run\'s results instead of reporting an error', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 1, items: [older] } as never);
    vi.mocked(apiClient.getRun).mockResolvedValue(older as never);
    vi.mocked(apiClient.getRunPerformance)
      .mockRejectedValueOnce(new apiClient.ApiError(409, 'being prepared'))
      .mockResolvedValue(makePerformance({ run_id: 'o1' }) as never);
    renderRuns('o1');

    expect(await screen.findByTestId('run-performance-pending')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PENDING_RETRY_MS + 10);
    });
    await waitFor(() => expect(screen.getByTestId('stat-row')).toBeInTheDocument());
    expect(screen.queryByTestId('run-performance-error')).not.toBeInTheDocument();
  });
});

describe('Run detail', () => {
  it('tells a queued run apart from a result', async () => {
    renderRuns('q1');
    const pending = await screen.findByTestId('run-pending');
    expect(pending).toHaveTextContent('Queued · #2 in line');
    expect(pending).toHaveTextContent('1 run ahead of it');
    expect(screen.getByRole('button', { name: /^cancel$/i })).toBeInTheDocument();
  });

  it('shows why a run failed and what kind of fix it needs', async () => {
    renderRuns('f1');
    expect(await screen.findByTestId('run-failed')).toHaveTextContent('Backtest failed · Data');
  });
});

describe('background runs', () => {
  it('picks up a run that finishes, and announces it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderRuns();
    await screen.findByTestId('runs-table');

    vi.mocked(apiClient.listRuns).mockResolvedValue({
      total: 3,
      items: [{ ...queued, status: 'completed', queue_position: null, signal_count: 3 }, failed, done],
    } as never);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS + 10);
    });

    await waitFor(() =>
      expect(within(screen.getByTestId('run-row-q1')).getByTestId('run-status')).toHaveTextContent('Completed'),
    );
    expect(screen.getByTestId('run-notices')).toHaveTextContent(/Momentum v3.*finished/);
  });

  it('stops polling once nothing is queued or running', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 1, items: [done] } as never);
    renderRuns();
    await screen.findByTestId('runs-table');
    const calls = vi.mocked(apiClient.listRuns).mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS * 3);
    });

    expect(vi.mocked(apiClient.listRuns).mock.calls.length).toBe(calls);
  });

  it('counts active runs for the tab badge', async () => {
    function Count() {
      return <span data-testid="count">{useRuns().activeCount}</span>;
    }
    render(
      <RunsProvider>
        <Count />
      </RunsProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'));
  });
});

describe('TabBar', () => {
  it('moves between tabs with the arrow keys and keeps one tab stop', async () => {
    function Harness() {
      const [value, setValue] = useState<'configure' | 'runs'>('configure');
      return (
        <TabBar
          label="Strategies"
          idPrefix="t"
          value={value}
          onChange={setValue}
          items={[
            { id: 'configure', label: 'Configure' },
            { id: 'runs', label: 'Runs', badge: 2, badgeLabel: '2 active' },
          ]}
        />
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    const configure = screen.getByRole('tab', { name: 'Configure' });
    const runsTab = screen.getByRole('tab', { name: 'Runs, 2 active' });
    expect(configure).toHaveAttribute('tabindex', '0');
    expect(runsTab).toHaveAttribute('tabindex', '-1');

    configure.focus();
    await user.keyboard('{ArrowRight}');

    expect(runsTab).toHaveAttribute('aria-selected', 'true');
    expect(runsTab).toHaveFocus();
  });
});

describe('executionSummary', () => {
  it('lists changed settings first and flags flattering defaults even when unchanged', () => {
    const items = executionSummary(
      { ...DEFAULT_EXECUTION, stop_loss_pct: 0.08, max_positions: 10 },
      'days',
    );
    expect(items.filter((item) => item.changed).map((item) => item.text)).toEqual([
      'max 10 positions',
      'stop 8%',
    ]);
    const costs = items.find((item) => item.key === 'costs');
    expect(costs?.changed).toBe(false);
    expect(costs?.caution).toMatch(/flatter/);
    expect(items.find((item) => item.key === 'fill_timing')?.caution).toMatch(/market-on-close/);
  });

  it('counts holding periods in bars on intraday runs', () => {
    const items = executionSummary({ ...DEFAULT_EXECUTION, cooldown_days: 3 }, 'bars');
    expect(items.find((item) => item.key === 'cooldown_days')?.text).toBe('cooldown 3 bars');
  });
});
