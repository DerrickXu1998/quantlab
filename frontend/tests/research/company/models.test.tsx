import { act, render, renderHook, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../../src/api/client';
import { ModelsPanel, signalModels } from '../../../src/research/company/ModelsPanel';
import {
  markerLabel,
  useModelOverlays,
  type ModelOverlay,
} from '../../../src/research/company/useModelOverlays';
import { makePerformance, makeRun } from '../../quantlab/fixtures';
import { adxFilter, catalog, rsiThreshold } from '../../strategies/fixtures';

vi.mock('../../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return { ...actual, createRun: vi.fn(), getRun: vi.fn(), getRunPerformance: vi.fn() };
});

const signal = (symbol: string, date: string, direction: 'bullish' | 'bearish') => ({
  symbol,
  date,
  direction,
  trigger_values: {},
  data_window_end: date,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.createRun).mockResolvedValue(makeRun({ id: 'run-7' }));
  vi.mocked(apiClient.getRun).mockResolvedValue(
    makeRun({
      id: 'run-7',
      signals: [
        signal('AAPL.US', '2024-01-02', 'bullish'),
        signal('AAPL.US', '2024-02-01', 'bearish'),
      ],
    }),
  );
  vi.mocked(apiClient.getRunPerformance).mockResolvedValue(makePerformance());
});

describe('signal models', () => {
  it('offers the models that say when, not the gates that read true on every bar', () => {
    const names = signalModels(catalog).map((model) => model.name);
    expect(names).toContain('rsi-threshold');
    expect(names).not.toContain(adxFilter.name);
  });

  it('labels each model on the chart by its first word', () => {
    expect(markerLabel('sma-crossover')).toBe('SMA');
    expect(markerLabel('breakout-20d')).toBe('BREAKOUT');
  });
});

describe('useModelOverlays', () => {
  it('runs the model over the one ticker and keeps its signals and results', async () => {
    const onRunCreated = vi.fn();
    const { result } = renderHook(() => useModelOverlays('AAPL.US', onRunCreated));

    await act(() =>
      result.current.apply({
        model: rsiThreshold,
        parameters: { period: 21 },
        symbol: 'AAPL.US',
        start: '2015-01-02',
        end: '2026-09-18',
      }),
    );

    expect(apiClient.createRun).toHaveBeenCalledWith({
      model_name: 'rsi-threshold',
      parameters: { period: 21 },
      symbols: ['AAPL.US'],
      start_date: '2015-01-02',
      end_date: '2026-09-18',
    });
    expect(onRunCreated).toHaveBeenCalled();
    const [overlay] = result.current.overlays;
    expect(overlay).toMatchObject({ status: 'ready', runId: 'run-7', visible: true });
    expect(overlay.signals).toHaveLength(2);
    expect(overlay.performance?.metrics).toBeDefined();
  });

  it('clears the overlays when the ticker changes, and drops results that land late', async () => {
    let finish: (run: apiClient.RunDetail) => void = () => {};
    vi.mocked(apiClient.getRun).mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { result, rerender } = renderHook(({ symbol }) => useModelOverlays(symbol), {
      initialProps: { symbol: 'AAPL.US' },
    });

    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.apply({
        model: rsiThreshold,
        parameters: {},
        symbol: 'AAPL.US',
        start: '2015-01-02',
        end: '2026-09-18',
      });
    });
    expect(result.current.overlays).toHaveLength(1);

    rerender({ symbol: 'MSFT.US' });
    expect(result.current.overlays).toHaveLength(0);

    // AAPL's markers must never be drawn on MSFT's chart.
    await act(async () => {
      finish(makeRun({ id: 'run-7', signals: [signal('AAPL.US', '2024-01-02', 'bullish')] }));
      await pending;
    });
    expect(result.current.overlays).toHaveLength(0);
  });

  it('explains a run that failed instead of drawing nothing', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(
      makeRun({ status: 'failed', error: 'no bars in window' }),
    );
    const { result } = renderHook(() => useModelOverlays('AAPL.US'));

    await act(() =>
      result.current.apply({
        model: rsiThreshold,
        parameters: {},
        symbol: 'AAPL.US',
        start: '2015-01-02',
        end: '2026-09-18',
      }),
    );

    expect(result.current.overlays[0]).toMatchObject({
      status: 'error',
      error: 'no bars in window',
    });
  });
});

function renderPanel(overlays: ModelOverlay[] = [], onApply = vi.fn()) {
  render(
    <ModelsPanel
      symbol="AAPL.US"
      catalog={catalog}
      catalogReady
      start="2015-01-02"
      end="2026-09-18"
      overlays={overlays}
      onApply={onApply}
      onToggle={vi.fn()}
      onRemove={vi.fn()}
    />,
  );
  return onApply;
}

describe('ModelsPanel', () => {
  it('sends only the parameters that were changed', async () => {
    const user = userEvent.setup();
    const onApply = renderPanel();

    await user.selectOptions(screen.getByLabelText('Model'), 'rsi-threshold');
    const period = screen.getByLabelText(/period/i);
    await user.clear(period);
    await user.type(period, '21');
    await user.click(screen.getByRole('button', { name: /apply to aapl\.us/i }));

    expect(onApply).toHaveBeenCalledWith(rsiThreshold, { period: 21 });
  });

  it('will not apply an out-of-range parameter', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.selectOptions(screen.getByLabelText('Model'), 'rsi-threshold');
    const period = screen.getByLabelText(/period/i);
    await user.clear(period);
    await user.type(period, '500');

    expect(screen.getByRole('button', { name: /apply to/i })).toBeDisabled();
    expect(period).toHaveAttribute('aria-invalid', 'true');
  });

  it("shows each applied model's outcome against simply holding the ticker", () => {
    renderPanel([
      {
        key: 'a',
        model: rsiThreshold,
        parameters: { period: 21 },
        status: 'ready',
        error: null,
        runId: 'run-7',
        signals: [signal('AAPL.US', '2024-01-02', 'bullish')],
        performance: makePerformance() as never,
        visible: true,
      },
    ]);

    const row = screen.getByTestId('model-overlay');
    expect(within(row).getByText('RSI')).toBeInTheDocument();
    expect(within(row).getByText('period=21')).toBeInTheDocument();
    expect(row).toHaveTextContent(/1 signals · \d+ trades/);
    expect(row).toHaveTextContent(/vs hold/);
  });

  it('does not offer filters, which belong in Strategies', () => {
    renderPanel();
    const options = within(screen.getByLabelText('Model'))
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(options).not.toContain('adx-trend-filter');
  });
});
