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
    listRuns: vi.fn(),
    getRun: vi.fn(),
    createRun: vi.fn(),
    getRunPerformance: vi.fn(),
    saveRun: vi.fn(),
    deleteRun: vi.fn(),
  };
});

vi.mock('../../src/quantlab/data/fundamentals', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/quantlab/data/fundamentals')>();
  return {
    ...actual,
    listFundamentalConcepts: vi.fn().mockResolvedValue({ symbol: 'ZZTRND', total: 0, items: [] }),
    getFundamentalSeries: vi.fn(),
  };
});

vi.mock('../../src/quantlab/data/customRules', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/quantlab/data/customRules')>();
  return {
    ...actual,
    listCustomRules: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    deleteCustomRule: vi.fn(),
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
  return user;
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

  it('names the document after the active destination', async () => {
    const user = userEvent.setup();
    renderApp();
    await waitFor(() => expect(document.title).toBe('Overview — QuantLab'));

    await user.click(screen.getByRole('button', { name: /market/i }));
    await waitFor(() => expect(document.title).toBe('Market — QuantLab'));
  });

  it('offers a skip link into the main landmark', () => {
    renderApp();

    const skip = screen.getByRole('link', { name: /skip to content/i });
    expect(skip).toHaveAttribute('href', '#main');
    expect(document.getElementById('main')).not.toBeNull();
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

  it('ships the simulation caveats alongside the figures', async () => {
    renderApp();

    const caveats = await screen.findByTestId('performance-assumptions');
    expect(caveats).toHaveTextContent(/not a tradeable strategy run/i);
    expect(caveats).toHaveTextContent(/no transaction costs/i);
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

    await user.click(within(guide).getByRole('button', { name: /run your first strategy/i }));
    await waitFor(() => expect(window.location.hash).toBe('#/strategies'));
  });

  it('distinguishes an unreachable backend from an empty one', async () => {
    vi.mocked(apiClient.listRuns).mockRejectedValue(new apiClient.ApiError(0, 'down'));

    renderApp();

    const error = await screen.findByTestId('overview-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('overview-no-runs')).not.toBeInTheDocument();
  });

  it('recovers from an unreachable backend through the retry action', async () => {
    vi.mocked(apiClient.listRuns).mockRejectedValueOnce(new apiClient.ApiError(0, 'down'));

    const user = userEvent.setup();
    renderApp();

    const error = await screen.findByTestId('overview-error');
    await user.click(within(error).getByRole('button', { name: /retry/i }));

    await waitFor(() => expect(apiClient.listRuns).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId('portfolio-summary')).toBeInTheDocument();
  });

  it('keeps the run and says why when a delete fails', async () => {
    vi.mocked(apiClient.listRuns).mockResolvedValue({
      total: 1,
      items: [makeRun({ name: 'base case' })],
    });
    vi.mocked(apiClient.deleteRun).mockRejectedValue(new apiClient.ApiError(500, 'read-only'));

    const user = userEvent.setup();
    renderApp();
    const rail = await screen.findByTestId('runs-rail');

    await user.click(within(rail).getByRole('button', { name: /delete run base case/i }));
    await user.click(within(rail).getByRole('button', { name: /confirm/i }));

    // The failure is announced on the row, and the run stays listed.
    expect(await within(rail).findByRole('alert')).toHaveTextContent(/read-only/i);
    expect(within(rail).getByText('base case')).toBeInTheDocument();
  });
});

describe('Strategies', () => {
  it('lists what the registry reports, with nothing about it hardcoded', async () => {
    await openStrategies();

    const list = await screen.findByTestId('model-list');
    expect(within(list).getByText('sma-crossover')).toBeInTheDocument();
    expect(within(list).getByText('v1.0.0')).toBeInTheDocument();
    // The count renders through the shared Numeric primitive, so the row's
    // text is split across elements; match on its full text.
    expect(
      within(list).getByText((_, element) => element?.textContent === '1 run'),
    ).toBeInTheDocument();
  });

  it('does not pretend a model is live or paper trading', async () => {
    await openStrategies();

    const list = await screen.findByTestId('model-list');
    // Simulation is the only mode the backend has, so it is the only one lit.
    expect(within(list).getByText('Simulated')).toBeInTheDocument();
    for (const label of ['Paper', 'Live']) {
      expect(within(list).getByText(label)).toHaveAttribute(
        'title',
        expect.stringMatching(/no execution backend/i),
      );
    }
  });

  it('generates the parameter form from declared metadata', async () => {
    await openStrategies();

    const field = (await screen.findByLabelText(/fast/i)) as HTMLInputElement;
    expect(field.value).toBe('20');
    expect(field.min).toBe('2');
    expect(field.max).toBe('100');
  });

  it('refuses to run until instruments are chosen', async () => {
    await openStrategies();
    await screen.findByLabelText(/fast/i);

    expect(screen.getByRole('button', { name: /run strategy/i })).toBeDisabled();
    expect(apiClient.createRun).not.toHaveBeenCalled();
  });

  it('submits only the parameters that were changed', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    const user = await openStrategies();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    await waitFor(() => expect(apiClient.createRun).toHaveBeenCalled());
    const [body] = vi.mocked(apiClient.createRun).mock.calls[0];
    expect(body.symbols).toEqual(['ZZTRND']);
    expect(body.parameters).toEqual({});
  });

  it('reports an out-of-range parameter against that field', async () => {
    const user = await openStrategies();

    const field = await screen.findByLabelText(/fast/i);
    await user.clear(field);
    await user.type(field, '500');

    expect(await screen.findByRole('alert')).toHaveTextContent(/<= 100/);
    expect(field).toHaveAttribute('aria-invalid', 'true');
  });

  it('shows the full results for a completed run, including the trade log', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    const user = await openStrategies();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    const results = await screen.findByTestId('run-results');
    expect(within(results).getByTestId('run-coverage')).toHaveTextContent('1/1');
    expect(within(results).getByTestId('run-dataset')).toHaveTextContent(/demo data/i);

    const log = await screen.findByTestId('trade-log');
    expect(within(log).getByText('ZZTRND')).toBeInTheDocument();
    // An unrealised position is labelled, not shown as a closed result.
    expect(within(log).getByText('Open')).toBeInTheDocument();
  });

  it('treats a zero-signal run as a result, not a failure', async () => {
    const empty = makeRun({ signal_count: 0, signals: [] });
    vi.mocked(apiClient.createRun).mockResolvedValue(empty);
    vi.mocked(apiClient.getRun).mockResolvedValue(empty);
    const user = await openStrategies();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    expect(await screen.findByTestId('run-empty')).toHaveTextContent(/no signals/i);
    expect(screen.queryByTestId('run-failed')).not.toBeInTheDocument();
  });

  it('renders a failed run distinctly from an empty one', async () => {
    const failed = makeRun({ status: 'failed', error: 'boom', signal_count: 0 });
    vi.mocked(apiClient.createRun).mockResolvedValue(failed);
    vi.mocked(apiClient.getRun).mockResolvedValue(failed);
    const user = await openStrategies();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    const failure = await screen.findByTestId('run-failed');
    expect(failure).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('run-empty')).not.toBeInTheDocument();
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
    const user = await openStrategies();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    const warning = await screen.findByTestId('run-corporate-actions');
    expect(warning).toHaveAttribute('role', 'alert');
    expect(warning).toHaveTextContent('2024-08-31');
  });

  it('saves an experiment under a name, which the run then wears', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.saveRun).mockResolvedValue(makeRun({ name: 'base case' }));
    const user = await openStrategies();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));
    await screen.findByTestId('run-results');

    await user.type(screen.getByLabelText(/experiment name/i), 'base case');
    await user.click(screen.getByRole('button', { name: /save experiment/i }));

    await waitFor(() => expect(apiClient.saveRun).toHaveBeenCalledWith('run-1', 'base case'));
    expect(await screen.findByTestId('run-saved-name')).toHaveTextContent('base case');
  });

  it('prefills the form from a signal-row handoff', async () => {
    window.location.hash = '#/strategies?model=sma-crossover&p_fast=50';
    renderApp();

    const field = (await screen.findByLabelText(/fast/i)) as HTMLInputElement;
    expect(field.value).toBe('50');
    // The named model is the one being configured.
    expect(
      await screen.findByRole('region', { name: /sma-crossover — strategy run/i }),
    ).toBeInTheDocument();
  });

  it('calls the surface a strategy run, and the rail Signal strategies', async () => {
    await openStrategies();

    expect(await screen.findByRole('region', { name: /signal strategies/i })).toBeInTheDocument();
    expect(
      await screen.findByRole('region', { name: /sma-crossover — strategy run/i }),
    ).toBeInTheDocument();
  });

  it('describes what each strategy fires on, composed from registry data', async () => {
    await openStrategies();

    const list = await screen.findByTestId('model-list');
    expect(within(list).getByTestId('fires-on-sma-crossover')).toHaveTextContent(
      'Fires bullish when fast crosses above slow',
    );
  });

  it('greets a first-timer with what a strategy run is, the form already usable', async () => {
    // No recorded runs: Overview has nothing to auto-load, so the run store is
    // genuinely empty when Strategies opens.
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
    await openStrategies();

    const intro = await screen.findByTestId('strategy-intro');
    expect(intro).toHaveTextContent(/what a strategy run is/i);
    expect(intro).toHaveTextContent(/execution criteria/i);
    expect(intro).toHaveTextContent(/nothing here trades/i);
    // The form it walks through is already on screen in the right column.
    expect(await screen.findByLabelText(/fast/i)).toBeInTheDocument();
    expect(screen.getByTestId('execution-fieldset')).toBeInTheDocument();
  });

  it('shows the simulation assumptions in the results column, not buried', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    const user = await openStrategies();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    const results = await screen.findByTestId('run-results');
    expect(await within(results).findByTestId('performance-assumptions')).toHaveTextContent(
      /not a tradeable strategy run/i,
    );
  });

  it('explains an empty registry across all three columns, not just the list', async () => {
    vi.mocked(apiClient.listModels).mockResolvedValue({ total: 0, items: [] });

    await openStrategies();

    expect(await screen.findByTestId('model-list-empty')).toHaveTextContent(
      /no models registered/i,
    );
    expect(await screen.findByTestId('lab-no-strategies')).toHaveTextContent(
      /no strategies to run/i,
    );
    expect(await screen.findByTestId('lab-nothing-to-configure')).toHaveTextContent(
      /nothing to configure/i,
    );
    expect(screen.queryByTestId('run-config')).not.toBeInTheDocument();
  });
});

describe('cross-destination run state', () => {
  it('a run created in Research is already selected in Strategies', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    const user = userEvent.setup();
    window.location.hash = '#/research';
    renderApp();

    // The Research dock renders every panel (the dockview mock), so the run
    // form is right there.
    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(await screen.findByRole('button', { name: /run strategy/i }));
    expect(await screen.findByTestId('run-results')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /strategies/i }));

    // No re-finding, no re-running: the same run is on screen.
    expect(await screen.findByTestId('run-results')).toBeInTheDocument();
    expect(apiClient.createRun).toHaveBeenCalledTimes(1);
  });

  it('"Watch in Overview" pins the run in the Overview rail', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    const user = await openStrategies();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));
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
