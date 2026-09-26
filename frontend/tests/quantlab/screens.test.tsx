import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import { DatasetProvider } from '../../src/api/DatasetProvider';
import { AppShell } from '../../src/chrome/AppShell';
import { RunsProvider } from '../../src/runs/RunsContext';
import { ThemeProvider } from '../../src/theme/ThemeProvider';
import { installCanvas2d, recordingFor } from '../mocks/canvas-2d';
import { installResizeObserver } from '../mocks/resize-observer';
import { makePerformance, makeRun, model } from './fixtures';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    getHealth: vi.fn(),
    listInstruments: vi.fn(),
    getPrices: vi.fn(),
    listSignals: vi.fn(),
    listModels: vi.fn(),
    listStrategies: vi.fn(),
    listStrategyTemplates: vi.fn(),
    listRuns: vi.fn(),
    getRun: vi.fn(),
    createRun: vi.fn(),
    createStrategyRun: vi.fn(),
    getRunPerformance: vi.fn(),
    saveRun: vi.fn(),
    deleteRun: vi.fn(),
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
  window.location.hash = '';
  vi.mocked(apiClient.getHealth).mockResolvedValue({
    status: 'ok',
    dataset: 'sqlite',
    seeded: true,
    signal_count: 933,
  });
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
  vi.mocked(apiClient.listSignals).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listModels).mockResolvedValue({ total: 1, items: [model] });
  vi.mocked(apiClient.listStrategies).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listStrategyTemplates).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 1, items: [makeRun()] });
  vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());
  vi.mocked(apiClient.getRunPerformance).mockResolvedValue(makePerformance());
});

function renderApp() {
  return render(
    <ThemeProvider>
      <DatasetProvider>
        <RunsProvider>
          <AppShell />
        </RunsProvider>
      </DatasetProvider>
    </ThemeProvider>,
  );
}

async function openStrategies() {
  const user = userEvent.setup();
  renderApp();
  await user.click(screen.getByRole('button', { name: /strategies/i }));
  await screen.findByTestId('signal-catalogue');
  return user;
}

/** A one-signal strategy on one ticker, run from the builder. */
async function runStrategy(user: ReturnType<typeof userEvent.setup>, symbol = 'ZZTRND') {
  await user.click(
    within(screen.getByTestId('signal-card-sma-crossover')).getByRole('button', { name: 'Entry' }),
  );
  await user.type(screen.getByLabelText(/add tickers/i), `${symbol}{Enter}`);
  await user.click(screen.getByRole('button', { name: /run backtest/i }));
}

describe('App shell', () => {
  it('canonicalises the empty hash to #/overview', async () => {
    renderApp();

    await waitFor(() => expect(window.location.hash).toBe('#/overview'));
  });

  it('maps the legacy #/lab hash to Overview rather than stranding it', async () => {
    window.location.hash = '#/lab';
    renderApp();

    await waitFor(() => expect(window.location.hash).toBe('#/overview'));
    expect(await screen.findByTestId('portfolio-summary')).toBeInTheDocument();
  });

  it('sends a bookmark to the retired Research Test mode to Strategies', async () => {
    window.location.hash = '#/research?mode=test';
    renderApp();

    await waitFor(() => expect(window.location.hash).toBe('#/strategies'));
    expect(await screen.findByTestId('signal-catalogue')).toBeInTheDocument();
  });

  it('navigates between destinations and follows the back button', async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByTestId('portfolio-summary');

    await user.click(screen.getByRole('button', { name: /market/i }));
    expect(await screen.findByRole('region', { name: /intraday/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /execution/i }));
    expect(await screen.findByTestId('order-ticket')).toBeInTheDocument();

    // The back button is a hashchange to the previous entry.
    window.location.hash = '#/overview';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(await screen.findByTestId('portfolio-summary')).toBeInTheDocument();
  });

  it('marks the feed as simulated in the header, and Execution in the nav', async () => {
    renderApp();

    const status = await screen.findByTestId('feed-status');
    expect(status).toHaveTextContent(/sim/i);
    expect(status).toHaveAttribute('title', expect.stringMatching(/no streaming feed/i));

    const execution = screen.getByRole('button', { name: /execution/i });
    expect(within(execution).getByText('sim')).toBeInTheDocument();
  });

  it('keeps the grain overlay out of the way of every control', () => {
    const { container } = renderApp();

    const grain = container.querySelector('.quantlab-grain');
    expect(grain).not.toBeNull();
    expect(grain).toHaveClass('pointer-events-none');
  });

  it('keeps the dataset disclosure in the shell on every destination', async () => {
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByTestId('dataset-badge')).toHaveTextContent(/demo data/i);

    await user.click(screen.getByRole('button', { name: /market/i }));
    expect(screen.getByTestId('dataset-badge')).toBeInTheDocument();
  });
});

describe('Overview', () => {
  it('falls back to the latest completed run when nothing is saved', async () => {
    renderApp();

    // The rail's saved view is empty and says how to fix it…
    expect(await screen.findByTestId('runs-rail-empty')).toHaveTextContent(
      /run and save an experiment/i,
    );
    // …while the main view still reports on the latest completed run.
    const summary = await screen.findByTestId('portfolio-summary');
    expect(within(summary).getByText(/\$112,000/)).toBeInTheDocument();
    expect(within(summary).getByText('+12.00%')).toBeInTheDocument();
  });

  it('never computes a metric itself', async () => {
    renderApp();
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

    renderApp();

    const row = await screen.findByTestId('stat-row');
    expect(within(row).getAllByText('—')).toHaveLength(2);
  });

  it('draws the equity curve rather than leaving an empty canvas', async () => {
    const { container } = renderApp();
    await screen.findByTestId('stat-row');

    await waitFor(() => {
      const canvas = container.querySelector('canvas');
      expect(canvas).not.toBeNull();
      expect(recordingFor(canvas as HTMLCanvasElement)?.strokes ?? 0).toBeGreaterThan(0);
    });
  });

  it('lists only the positions still open, and tags the live column', async () => {
    renderApp();

    const positions = await screen.findByTestId('positions-table');
    expect(within(positions).getByText('ZZMEAN')).toBeInTheDocument();
    // The closed trade belongs in the trade log, not in open positions.
    expect(within(positions).queryByText('ZZTRND')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('simulated-tag').length).toBeGreaterThan(0);
  });

  it('ships the backtest caveats alongside the figures, open rather than folded away', async () => {
    renderApp();

    // Derived from the run's own execution config now, so they are real
    // information about this run and are not hidden behind a disclosure.
    const caveats = await screen.findByTestId('performance-assumptions');
    expect(caveats).toHaveTextContent(/what this run assumed/i);
    expect(caveats).toHaveTextContent(/no transaction costs/i);
    expect(caveats.querySelector('details')).toBeNull();
  });

  it('makes saved runs the primary content of the rail', async () => {
    const saved = makeRun({
      id: 'run-saved',
      name: 'base case',
      created_at: '2026-09-18T12:00:00Z',
    });
    vi.mocked(apiClient.listRuns).mockResolvedValue({
      total: 2,
      items: [saved, makeRun()],
    });
    vi.mocked(apiClient.getRun).mockImplementation((id: string) =>
      Promise.resolve(makeRun({ id, name: id === 'run-saved' ? 'base case' : null })),
    );

    const user = userEvent.setup();
    renderApp();
    await screen.findByTestId('portfolio-summary');

    const rail = screen.getByTestId('runs-rail');
    // Saved is the default filter: the unnamed run stays out of it.
    expect(within(rail).getByText('base case')).toBeInTheDocument();
    expect(within(rail).queryByText('sma-crossover')).toBeNull();

    await user.click(within(rail).getByRole('button', { name: 'all' }));
    expect(within(rail).getByText('sma-crossover')).toBeInTheDocument();
  });

  it('loads a saved run into the hero when its row is selected', async () => {
    const saved = makeRun({
      id: 'run-saved',
      name: 'base case',
      created_at: '2026-09-18T12:00:00Z',
    });
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 1, items: [saved] });
    vi.mocked(apiClient.getRun).mockImplementation((id: string) =>
      Promise.resolve(makeRun({ id, name: 'base case' })),
    );

    const user = userEvent.setup();
    renderApp();
    const rail = await screen.findByTestId('runs-rail');

    await user.click(within(rail).getByText('base case'));

    await waitFor(() => expect(window.location.hash).toBe('#/overview?run=run-saved'));
    await waitFor(() =>
      expect(vi.mocked(apiClient.getRunPerformance).mock.calls.at(-1)?.[0]).toBe('run-saved'),
    );
    expect(await screen.findByTestId('portfolio-summary')).toBeInTheDocument();
  });

  it('deletes a run behind a confirm step', async () => {
    vi.mocked(apiClient.listRuns).mockResolvedValue({
      total: 1,
      items: [makeRun({ name: 'base case' })],
    });
    vi.mocked(apiClient.deleteRun).mockResolvedValue(undefined);

    const user = userEvent.setup();
    renderApp();
    const rail = await screen.findByTestId('runs-rail');

    await user.click(within(rail).getByRole('button', { name: /delete run base case/i }));
    // Armed, not fired: the first click only reveals the confirm step.
    expect(apiClient.deleteRun).not.toHaveBeenCalled();

    await user.click(within(rail).getByRole('button', { name: /confirm/i }));

    await waitFor(() => expect(apiClient.deleteRun).toHaveBeenCalledWith('run-1'));
    await waitFor(() => expect(within(rail).queryByText('base case')).toBeNull());
  });

  it('guides the first run when no runs exist at all', async () => {
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });

    const user = userEvent.setup();
    renderApp();

    const guide = await screen.findByTestId('overview-no-runs');
    expect(guide).toHaveTextContent(/no runs yet/i);
    // Step 1 names the dataset; step 3 cites the stored signal count.
    expect(within(guide).getByTestId('dataset-badge')).toHaveTextContent(/demo data/i);
    expect(guide).toHaveTextContent('933');
    expect(screen.queryByTestId('portfolio-summary')).not.toBeInTheDocument();

    await user.click(within(guide).getByRole('button', { name: /run your first backtest/i }));
    await waitFor(() => expect(window.location.hash).toBe('#/strategies'));
  });

  it('distinguishes an unreachable backend from an empty one', async () => {
    vi.mocked(apiClient.listRuns).mockRejectedValue(new apiClient.ApiError(0, 'down'));

    renderApp();

    const error = await screen.findByTestId('overview-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('overview-no-runs')).not.toBeInTheDocument();
  });
});

describe('Strategies', () => {
  /**
   * The reported problem: Research and Strategies could not be told apart,
   * because Strategies carried a single-rule lab and a filings inspector that
   * were Research's Test and Company views again.
   */
  it('is one builder, without the tabs that duplicated Research', async () => {
    await openStrategies();

    expect(screen.queryByRole('tab', { name: /signal lab/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /point-in-time/i })).not.toBeInTheDocument();
    expect(screen.getByText(/combine several signals/i)).toBeInTheDocument();
  });

  it('draws its universe from the whole catalogue, not the eight-name watchlist', async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({
      symbol: `ZZ${i}.US`,
      name: `Company ${i}`,
      currency: 'USD',
      regime: null,
    })) as unknown as apiClient.Instrument[];
    vi.mocked(apiClient.listInstruments).mockResolvedValue({ total: many.length, items: many });

    await openStrategies();

    expect(await screen.findByRole('button', { name: /all us\s*12/i })).toBeInTheDocument();
  });

  it('refuses to run until the strategy has a signal and a universe', async () => {
    const user = await openStrategies();
    const run = screen.getByRole('button', { name: /run backtest/i });
    expect(run).toBeDisabled();

    await user.click(
      within(screen.getByTestId('signal-card-sma-crossover')).getByRole('button', {
        name: 'Entry',
      }),
    );
    expect(run).toBeDisabled();
    expect(apiClient.createStrategyRun).not.toHaveBeenCalled();
  });

  it('runs the strategy over its universe and shows the results with the trade log', async () => {
    vi.mocked(apiClient.createStrategyRun).mockResolvedValue(makeRun());
    const user = await openStrategies();

    await runStrategy(user);

    await waitFor(() => expect(apiClient.createStrategyRun).toHaveBeenCalledTimes(1));
    const [body] = vi.mocked(apiClient.createStrategyRun).mock.calls[0];
    expect(body.symbols).toEqual(['ZZTRND']);
    expect(body.strategy?.components).toHaveLength(1);

    const results = await screen.findByTestId('run-results');
    expect(within(results).getByTestId('run-coverage')).toHaveTextContent('1/1');
    const log = await screen.findByTestId('trade-log');
    expect(within(log).getByText('ZZTRND')).toBeInTheDocument();
  });

  it('saves an experiment under a name, which the run then wears', async () => {
    vi.mocked(apiClient.createStrategyRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.saveRun).mockResolvedValue(makeRun({ name: 'base case' }));
    const user = await openStrategies();

    await runStrategy(user);
    await screen.findByTestId('run-results');

    await user.type(screen.getByLabelText(/experiment name/i), 'base case');
    await user.click(screen.getByRole('button', { name: /save experiment/i }));

    await waitFor(() => expect(apiClient.saveRun).toHaveBeenCalledWith('run-1', 'base case'));
    expect(await screen.findByTestId('run-saved-name')).toHaveTextContent('base case');
  });

  it('turns a signal-row handoff into the first entry signal, on the ticker it fired on', async () => {
    window.location.hash = '#/strategies?model=sma-crossover&p_fast=50&symbol=ZZTRND';
    renderApp();

    expect(await screen.findByText(/sma-crossover added as entry/i)).toBeInTheDocument();
    expect(screen.getByTestId('universe-count')).toHaveTextContent(/1 ticker/i);
    expect(screen.getByDisplayValue('50')).toBeInTheDocument();
  });
});

describe('cross-destination run state', () => {
  it('a strategy run is still on screen after visiting another destination', async () => {
    vi.mocked(apiClient.createStrategyRun).mockResolvedValue(makeRun());
    const user = await openStrategies();

    await runStrategy(user);
    expect(await screen.findByTestId('run-results')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /research/i }));
    await user.click(screen.getByRole('button', { name: /strategies/i }));

    // No re-running: the same run comes back from the shared store.
    expect(await screen.findByTestId('run-results')).toBeInTheDocument();
    expect(apiClient.createStrategyRun).toHaveBeenCalledTimes(1);
  });

  it('"Watch in Overview" pins the run in the Overview rail', async () => {
    vi.mocked(apiClient.createStrategyRun).mockResolvedValue(makeRun());
    const user = await openStrategies();

    await runStrategy(user);
    await screen.findByTestId('run-results');

    await user.click(screen.getByRole('button', { name: /watch in overview/i }));

    await waitFor(() => expect(window.location.hash).toBe('#/overview?run=run-1'));
    expect(await screen.findByTestId('portfolio-summary')).toBeInTheDocument();
  });
});

describe('Composition', () => {
  it('breaks the grid once, on purpose', async () => {
    // The brief asks for a deliberate overlap rather than a column of cards.
    // Pinned by a test because it is the kind of detail a later refactor
    // flattens without noticing.
    const { container } = renderApp();
    await screen.findByTestId('stat-row');

    const chips = container.querySelector('.-top-3');
    expect(chips).not.toBeNull();
    // It overlaps the panel edge, so it must not block what is underneath.
    expect(chips).toHaveClass('pointer-events-none');
  });
});
