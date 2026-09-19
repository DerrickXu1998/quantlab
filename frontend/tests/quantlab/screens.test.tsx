import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import { QuantLabPage } from '../../src/quantlab/QuantLabPage';
import { installCanvas2d, recordingFor } from '../mocks/canvas-2d';
import { installResizeObserver } from '../mocks/resize-observer';
import { makePerformance, makeRun, model } from './fixtures';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listInstruments: vi.fn(),
    getPrices: vi.fn(),
    listModels: vi.fn(),
    listRuns: vi.fn(),
    getRun: vi.fn(),
    createRun: vi.fn(),
    getRunPerformance: vi.fn(),
  };
});

installResizeObserver();
installCanvas2d();

const instruments = [
  { symbol: 'ZZTRND', name: 'Trend Co', currency: 'USD', regime: null },
  { symbol: 'ZZMEAN', name: 'Mean Co', currency: 'USD', regime: null },
] as unknown as apiClient.Instrument[];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listInstruments).mockResolvedValue({
    total: instruments.length,
    items: instruments,
  });
  vi.mocked(apiClient.getPrices).mockResolvedValue({
    total: 1,
    items: [
      { date: '2024-12-31', open: 10, high: 11, low: 9, close: 10.5, volume: 100 },
    ] as unknown as apiClient.PriceBar[],
  });
  vi.mocked(apiClient.listModels).mockResolvedValue({ total: 1, items: [model] });
  vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 1, items: [makeRun()] });
  vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());
  vi.mocked(apiClient.getRunPerformance).mockResolvedValue(makePerformance());
});

function renderLab() {
  return render(<QuantLabPage onExit={() => {}} />);
}

describe('Quant Lab surface', () => {
  it('scopes its palette to itself so the Signal Viewer theme is untouched', () => {
    const { container } = renderLab();

    expect(container.querySelector('.quantlab')).not.toBeNull();
    expect(document.documentElement.classList.contains('quantlab')).toBe(false);
  });

  it('keeps the grain overlay out of the way of every control', () => {
    const { container } = renderLab();

    const grain = container.querySelector('.quantlab-grain');
    expect(grain).not.toBeNull();
    expect(grain).toHaveClass('pointer-events-none');
  });

  it('offers a way back to the Signal Viewer', async () => {
    const onExit = vi.fn();
    const user = userEvent.setup();
    render(<QuantLabPage onExit={onExit} />);

    await user.click(screen.getByRole('button', { name: /signal viewer/i }));

    expect(onExit).toHaveBeenCalled();
  });

  it('marks the feed as simulated without being asked', async () => {
    renderLab();

    const status = await screen.findByTestId('feed-status');
    expect(status).toHaveTextContent(/sim/i);
    expect(status).toHaveAttribute('title', expect.stringMatching(/no streaming feed/i));
  });
});

describe('Overview', () => {
  it('reports on the most recent completed run, with the backend\'s own numbers', async () => {
    renderLab();

    const summary = await screen.findByTestId('portfolio-summary');
    expect(within(summary).getByText(/\$112,000/)).toBeInTheDocument();
    expect(within(summary).getByText('+12.00%')).toBeInTheDocument();
  });

  it('never computes a metric itself', async () => {
    renderLab();
    await screen.findByTestId('stat-row');

    // Every figure on the row came off the wire; the browser reduced nothing.
    expect(apiClient.getRunPerformance).toHaveBeenCalledWith('run-1');
    const row = screen.getByTestId('stat-row');
    expect(row).toHaveTextContent('1.84'); // sharpe
    expect(row).toHaveTextContent('-7.00%'); // max drawdown
    expect(row).toHaveTextContent('60.00%'); // win rate
  });

  it('shows a dash where a metric is not measurable, never a zero', async () => {
    vi.mocked(apiClient.getRunPerformance).mockResolvedValue(
      makePerformance({
        metrics: { ...makePerformance().metrics, sharpe_ratio: null, win_rate: null },
      }),
    );

    renderLab();

    const row = await screen.findByTestId('stat-row');
    expect(within(row).getAllByText('—')).toHaveLength(2);
  });

  it('draws the equity curve rather than leaving an empty canvas', async () => {
    const { container } = renderLab();
    await screen.findByTestId('stat-row');

    await waitFor(() => {
      const canvas = container.querySelector('canvas');
      expect(canvas).not.toBeNull();
      expect(recordingFor(canvas as HTMLCanvasElement)?.strokes ?? 0).toBeGreaterThan(0);
    });
  });

  it('lists only the positions still open, and tags the live column', async () => {
    renderLab();

    const positions = await screen.findByTestId('positions-table');
    expect(within(positions).getByText('ZZMEAN')).toBeInTheDocument();
    // The closed trade belongs in the trade log, not in open positions.
    expect(within(positions).queryByText('ZZTRND')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('simulated-tag').length).toBeGreaterThan(0);
  });

  it('ships the backtest caveats alongside the figures', async () => {
    renderLab();

    const caveats = await screen.findByTestId('performance-assumptions');
    expect(caveats).toHaveTextContent(/not a tradeable backtest/i);
    expect(caveats).toHaveTextContent(/no transaction costs/i);
  });

  it('explains an absence of runs instead of showing an empty book', async () => {
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });

    renderLab();

    expect(await screen.findByTestId('overview-no-runs')).toHaveTextContent(/no runs yet/i);
    expect(screen.queryByTestId('portfolio-summary')).not.toBeInTheDocument();
  });

  it('distinguishes an unreachable backend from an empty one', async () => {
    vi.mocked(apiClient.listRuns).mockRejectedValue(new apiClient.ApiError(0, 'down'));

    renderLab();

    const error = await screen.findByTestId('overview-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('overview-no-runs')).not.toBeInTheDocument();
  });

  it('says the feed is disconnected rather than showing a blank rail', async () => {
    vi.mocked(apiClient.listInstruments).mockRejectedValue(new apiClient.ApiError(0, 'down'));

    renderLab();

    expect(await screen.findByTestId('watchlist-disconnected')).toHaveTextContent(
      /feed disconnected/i,
    );
  });
});

describe('Strategy Lab', () => {
  async function openLab() {
    const user = userEvent.setup();
    renderLab();
    await user.click(screen.getByRole('button', { name: /strategy lab/i }));
    return user;
  }

  it('lists what the registry reports, with nothing about it hardcoded', async () => {
    await openLab();

    const list = await screen.findByTestId('strategy-list');
    expect(within(list).getByText('sma-crossover')).toBeInTheDocument();
    expect(within(list).getByText('v1.0.0')).toBeInTheDocument();
    expect(within(list).getByText(/1 run/)).toBeInTheDocument();
  });

  it('does not pretend a strategy is live or paper trading', async () => {
    await openLab();

    const list = await screen.findByTestId('strategy-list');
    // BACKTEST is the only mode the backend has, so it is the only one lit.
    expect(within(list).getByText('Backtest')).toBeInTheDocument();
    for (const label of ['Paper', 'Live']) {
      expect(within(list).getByText(label)).toHaveAttribute(
        'title',
        expect.stringMatching(/no execution backend/i),
      );
    }
  });

  it('generates the parameter form from declared metadata', async () => {
    await openLab();

    const field = (await screen.findByLabelText(/fast/i)) as HTMLInputElement;
    expect(field.value).toBe('20');
    expect(field.min).toBe('2');
    expect(field.max).toBe('100');
  });

  it('refuses to run until instruments are chosen', async () => {
    await openLab();
    await screen.findByLabelText(/fast/i);

    expect(screen.getByRole('button', { name: /run backtest/i })).toBeDisabled();
    expect(apiClient.createRun).not.toHaveBeenCalled();
  });

  it('submits only the parameters that were changed', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    const user = await openLab();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run backtest/i }));

    await waitFor(() => expect(apiClient.createRun).toHaveBeenCalled());
    const [body] = vi.mocked(apiClient.createRun).mock.calls[0];
    expect(body.symbols).toEqual(['ZZTRND']);
    expect(body.parameters).toEqual({});
  });

  it('reports an out-of-range parameter against that field', async () => {
    const user = await openLab();

    const field = await screen.findByLabelText(/fast/i);
    await user.clear(field);
    await user.type(field, '500');

    expect(await screen.findByRole('alert')).toHaveTextContent(/<= 100/);
    expect(field).toHaveAttribute('aria-invalid', 'true');
  });

  it('shows the trade log for a completed run', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    const user = await openLab();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run backtest/i }));

    const log = await screen.findByTestId('trade-log');
    expect(within(log).getByText('ZZTRND')).toBeInTheDocument();
    // An unrealised position is labelled, not shown as a closed result.
    expect(within(log).getByText('Open')).toBeInTheDocument();
  });

  it('treats a zero-signal run as a result, not a failure', async () => {
    const empty = makeRun({ signal_count: 0, signals: [] });
    vi.mocked(apiClient.createRun).mockResolvedValue(empty);
    vi.mocked(apiClient.getRun).mockResolvedValue(empty);
    const user = await openLab();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run backtest/i }));

    expect(await screen.findByTestId('lab-run-empty')).toHaveTextContent(/no signals/i);
    expect(screen.queryByTestId('lab-run-failed')).not.toBeInTheDocument();
  });

  it('renders a failed run distinctly from an empty one', async () => {
    const failed = makeRun({ status: 'failed', error: 'boom', signal_count: 0 });
    vi.mocked(apiClient.createRun).mockResolvedValue(failed);
    vi.mocked(apiClient.getRun).mockResolvedValue(failed);
    const user = await openLab();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run backtest/i }));

    const failure = await screen.findByTestId('lab-run-failed');
    expect(failure).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('lab-run-empty')).not.toBeInTheDocument();
  });

  it('always shows coverage beside the signal count', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    const user = await openLab();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run backtest/i }));

    const coverage = await screen.findByTestId('lab-run-coverage');
    expect(coverage).toHaveTextContent('1/1');
    expect(coverage).toHaveTextContent(/demo data/i);
  });

  it('warns about unadjusted corporate actions in the window', async () => {
    const withSplit = makeRun({
      corporate_actions: [
        {
          instrument_id: 1,
          symbol: 'ZZTRND',
          ex_date: '2024-08-31',
          action_type: 'split',
          split_ratio: 4,
          dividend: null,
        },
      ],
    });
    vi.mocked(apiClient.createRun).mockResolvedValue(withSplit);
    vi.mocked(apiClient.getRun).mockResolvedValue(withSplit);
    const user = await openLab();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run backtest/i }));

    const warning = await screen.findByTestId('lab-corporate-actions');
    expect(warning).toHaveAttribute('role', 'alert');
    expect(warning).toHaveTextContent('2024-08-31');
  });

  it('explains an empty registry instead of showing a blank list', async () => {
    vi.mocked(apiClient.listModels).mockResolvedValue({ total: 0, items: [] });

    await openLab();

    expect(await screen.findByTestId('strategies-empty')).toHaveTextContent(
      /no strategies registered/i,
    );
  });
});

describe('Composition', () => {
  it('breaks the grid once, on purpose', async () => {
    // The brief asks for a deliberate overlap rather than a column of cards.
    // Pinned by a test because it is the kind of detail a later refactor
    // flattens without noticing.
    const { container } = renderLab();
    await screen.findByTestId('stat-row');

    const chips = container.querySelector('.-top-3');
    expect(chips).not.toBeNull();
    // It overlaps the panel edge, so it must not block what is underneath.
    expect(chips).toHaveClass('pointer-events-none');
  });
});
