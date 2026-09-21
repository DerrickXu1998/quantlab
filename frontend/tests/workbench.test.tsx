import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../src/api/client';
import { ModelList } from '../src/components/ModelList';
import { RunConfigForm } from '../src/components/RunConfigForm';
import { RunResultsView } from '../src/components/RunResultsView';
import { RunsProvider, useRuns } from '../src/runs/RunsContext';
import { WorkspaceProvider, useWorkspace } from '../src/workspace/WorkspaceContext';
import { makeInstrument } from './fixtures';

vi.mock('../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listModels: vi.fn(),
    listInstruments: vi.fn(),
    listSignals: vi.fn(),
    listRuns: vi.fn(),
    getPrices: vi.fn(),
    createRun: vi.fn(),
    getRun: vi.fn(),
    getRunPerformance: vi.fn(),
    saveRun: vi.fn(),
    deleteRun: vi.fn(),
  };
});

vi.mock('../src/quantlab/data/customRules', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/quantlab/data/customRules')>();
  return {
    ...actual,
    listCustomRules: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    deleteCustomRule: vi.fn(),
  };
});

/**
 * A model the front end has never heard of, with a parameter name that appears
 * nowhere in the source. If the form renders it correctly, nothing about model
 * identity is hardcoded (SC-002).
 */
const inventedModel: apiClient.Model = {
  name: 'zeta-reversion',
  version: '2.1.0',
  lookback_days: 30,
  scale_class: 'scale_free',
  direction_semantics: 'bullish when zeta crosses up',
  origin: 'builtin',
  custom_rule_id: null,
  template: null,
  parameters: [
    {
      name: 'zeta_threshold',
      type: 'int',
      default: 12,
      minimum: 2,
      maximum: 40,
      choices: null,
      description: 'Invented parameter.',
    },
  ],
};

function makeRun(overrides: Partial<apiClient.RunDetail> = {}): apiClient.RunDetail {
  return {
    id: 'run-1',
    name: null,
    model_name: 'zeta-reversion',
    model_version: '2.1.0',
    parameters: { zeta_threshold: 12 },
    symbols: ['ZZTRND'],
    start_date: '2024-01-01',
    end_date: '2024-12-31',
    status: 'completed',
    error: null,
    created_at: '2026-09-19T12:00:00Z',
    signal_count: 1,
    coverage: {
      instruments_requested: 3,
      instruments_with_data: 2,
      instruments_full_warmup: 1,
    },
    model_available: true,
    dataset: 'sqlite',
    instrument_ids: null,
    ingest_run_ids: null,
    corporate_actions: [],
    re_runnable: true,
    signals: [
      {
        symbol: 'ZZTRND',
        date: '2024-03-15',
        direction: 'bullish',
        trigger_values: { zeta: 1.5 },
        data_window_end: '2024-03-15',
      },
    ],
    ...overrides,
  };
}

/** The merged pieces, wired the way the destinations wire them. */
function Harness({ results = false }: { results?: boolean }) {
  const {
    modelEntries,
    modelsStatus,
    selectedModel,
    selectModel,
    activeRun,
    inFlight,
    start,
    cancel,
  } = useRuns();
  const { instruments } = useWorkspace();

  if (modelsStatus !== 'ready') return null;
  return (
    <>
      <ModelList
        entries={modelEntries}
        selected={selectedModel?.name ?? null}
        onSelect={(name) =>
          selectModel(modelEntries.find((entry) => entry.model.name === name)?.model ?? null)
        }
      />
      {selectedModel ? (
        <RunConfigForm
          model={selectedModel}
          instruments={instruments}
          running={inFlight}
          onRun={(body) => void start(body)}
          onCancel={cancel}
        />
      ) : null}
      {results && activeRun ? <RunResultsView run={activeRun} /> : null}
    </>
  );
}

function renderWorkbench(ui: React.ReactNode) {
  return render(
    <WorkspaceProvider>
      <RunsProvider>{ui}</RunsProvider>
    </WorkspaceProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = '';
  vi.mocked(apiClient.listModels).mockResolvedValue({ total: 1, items: [inventedModel] });
  vi.mocked(apiClient.listInstruments).mockResolvedValue({
    total: 1,
    items: [makeInstrument()],
  });
  vi.mocked(apiClient.listSignals).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.getPrices).mockResolvedValue({ total: 0, items: [] });
});

describe('ModelList', () => {
  it('lists whatever the backend registry reports, including unknown models', async () => {
    renderWorkbench(<Harness />);

    expect(await screen.findByText('zeta-reversion')).toBeInTheDocument();
    expect(screen.getByText('v2.1.0')).toBeInTheDocument();
    // The list is honest about what a model is: no live or paper pretence.
    expect(screen.getByText('Simulated')).toBeInTheDocument();
  });

  it('composes each strategy’s fires-on line from the registry’s own fields', async () => {
    renderWorkbench(<Harness />);

    // direction_semantics arrives as "bullish when zeta crosses up"; the card
    // renders it as a plain sentence, with no per-model copy in the frontend.
    expect(await screen.findByTestId('fires-on-zeta-reversion')).toHaveTextContent(
      'Fires bullish when zeta crosses up',
    );
  });
});

describe('RunConfigForm', () => {
  it('generates the parameter form from declared metadata', async () => {
    renderWorkbench(<Harness />);

    const field = (await screen.findByLabelText(/zeta_threshold/i)) as HTMLInputElement;
    expect(field.value).toBe('12'); // seeded from the declared default
    expect(field.min).toBe('2');
    expect(field.max).toBe('40');
  });

  it('reports an out-of-range value against that specific parameter', async () => {
    const user = userEvent.setup();
    renderWorkbench(<Harness />);

    const field = await screen.findByLabelText(/zeta_threshold/i);
    await user.clear(field);
    await user.type(field, '99');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/zeta_threshold/);
    expect(alert).toHaveTextContent(/<= 40/);
    expect(field).toHaveAttribute('aria-invalid', 'true');
    // No run may be attempted while a parameter is invalid.
    expect(apiClient.createRun).not.toHaveBeenCalled();
  });

  it('submits only overrides, leaving untouched parameters to their defaults', async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());

    renderWorkbench(<Harness />);

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(await screen.findByRole('button', { name: /run strategy/i }));

    await waitFor(() => expect(apiClient.createRun).toHaveBeenCalled());
    const [body] = vi.mocked(apiClient.createRun).mock.calls[0];
    expect(body.model_name).toBe('zeta-reversion');
    expect(body.symbols).toEqual(['ZZTRND']);
    // The default was not modified, so it is not sent as an override.
    expect(body.parameters).toEqual({});
  });

  it('renders the execution fieldset seeded with the API defaults', async () => {
    renderWorkbench(<Harness />);

    const fieldset = await screen.findByTestId('execution-fieldset');
    expect(within(fieldset).getByLabelText(/initial capital/i)).toHaveValue(100000);
    expect(within(fieldset).getByLabelText(/position sizing/i)).toHaveValue('equal_weight');
    expect(within(fieldset).getByLabelText(/transaction cost/i)).toHaveValue(0);
    expect(within(fieldset).getByLabelText(/entry price/i)).toHaveValue('same_close');
    // Optional fields seed empty: uncapped, no stops.
    expect((within(fieldset).getByLabelText(/max open positions/i) as HTMLInputElement).value).toBe(
      '',
    );
    expect((within(fieldset).getByLabelText(/stop loss/i) as HTMLInputElement).value).toBe('');
  });

  it('shows the fraction field only for fixed-fraction sizing', async () => {
    const user = userEvent.setup();
    renderWorkbench(<Harness />);

    const fieldset = await screen.findByTestId('execution-fieldset');
    expect(within(fieldset).queryByLabelText(/fraction per entry/i)).not.toBeInTheDocument();

    await user.selectOptions(within(fieldset).getByLabelText(/position sizing/i), 'fixed_fraction');

    expect(within(fieldset).getByLabelText(/fraction per entry/i)).toHaveValue(0.1);
  });

  it('flags an out-of-range execution value against that field and blocks the run', async () => {
    const user = userEvent.setup();
    renderWorkbench(<Harness />);

    const field = await screen.findByLabelText(/stop loss/i);
    await user.type(field, '2');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/stop loss/i);
    expect(alert).toHaveTextContent(/<= 1/);
    expect(field).toHaveAttribute('aria-invalid', 'true');
    // No run may be attempted while an execution criterion is invalid.
    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    expect(screen.getByRole('button', { name: /run strategy/i })).toBeDisabled();
    expect(apiClient.createRun).not.toHaveBeenCalled();
  });

  it('submits the merged execution criteria with the run', async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());

    renderWorkbench(<Harness />);

    const capital = await screen.findByLabelText(/initial capital/i);
    await user.clear(capital);
    await user.type(capital, '50000');
    await user.type(await screen.findByLabelText(/stop loss/i), '0.1');
    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    await waitFor(() => expect(apiClient.createRun).toHaveBeenCalled());
    const [body] = vi.mocked(apiClient.createRun).mock.calls[0];
    expect(body.execution).toEqual({
      initial_capital: 50000,
      position_sizing: 'equal_weight',
      fraction: 0.1,
      max_open_positions: null,
      transaction_cost_bps: 0,
      fixed_cost_per_trade: 0,
      stop_loss_pct: 0.1,
      take_profit_pct: null,
      entry_price: 'same_close',
    });
  });

  it('submits fixed-fraction sizing with its fraction', async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());

    renderWorkbench(<Harness />);

    await user.selectOptions(await screen.findByLabelText(/position sizing/i), 'fixed_fraction');
    const fraction = await screen.findByLabelText(/fraction per entry/i);
    await user.clear(fraction);
    await user.type(fraction, '0.25');
    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    await waitFor(() => expect(apiClient.createRun).toHaveBeenCalled());
    const [body] = vi.mocked(apiClient.createRun).mock.calls[0];
    expect(body.execution).toMatchObject({ position_sizing: 'fixed_fraction', fraction: 0.25 });
  });
});

describe('RunResultsView', () => {
  beforeEach(() => {
    vi.mocked(apiClient.getRunPerformance).mockResolvedValue({
      run_id: 'run-1',
      initial_capital: 100_000,
      equity: [
        { date: '2024-01-01', value: 100_000 },
        { date: '2024-01-02', value: 112_000 },
      ],
      benchmark: [
        { date: '2024-01-01', value: 100_000 },
        { date: '2024-01-02', value: 103_000 },
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
      trades: [],
      assumptions: [],
    });
  });

  function renderResults(run: apiClient.RunDetail) {
    return render(
      <RunsProvider>
        <RunResultsView run={run} />
      </RunsProvider>,
    );
  }

  it('always shows coverage alongside the signal count', () => {
    renderResults(makeRun());

    const coverage = screen.getByTestId('run-coverage');
    expect(within(coverage).getByTestId('signal-count')).toHaveTextContent('1');
    // The denominator is never omitted: 2 of 3 had data, 1 of 3 had warm-up.
    expect(coverage).toHaveTextContent('2/3');
    expect(coverage).toHaveTextContent('1/3');
  });

  it('fetches the backend performance for a populated run', async () => {
    renderResults(makeRun());

    await waitFor(() => expect(apiClient.getRunPerformance).toHaveBeenCalledWith('run-1'));
    expect(await screen.findByTestId('stat-row')).toHaveTextContent('1.84');
  });

  it('renders a zero-signal run as a result, not a failure', () => {
    renderResults(makeRun({ signal_count: 0, signals: [] }));

    const empties = screen.getByTestId('run-empty');
    expect(empties).toHaveTextContent(/no signals/i);
    // Decisively: not an error treatment, and no failure state.
    expect(screen.queryByTestId('run-failed')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    // Coverage is still reported for an empty result.
    expect(screen.getByTestId('run-coverage')).toBeInTheDocument();
  });

  it('renders a failed run distinctly from an empty one', () => {
    renderResults(
      makeRun({ status: 'failed', error: 'something broke', signal_count: 0, signals: [] }),
    );

    expect(screen.getByTestId('run-failed')).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('run-empty')).not.toBeInTheDocument();
  });

  it('shows which dataset produced the result', () => {
    renderResults(makeRun({ dataset: 'warehouse' }));

    expect(screen.getByTestId('run-dataset')).toHaveTextContent(/live history/i);
  });

  it('marks demo results plainly, so they cannot pass for real ones', () => {
    renderResults(makeRun({ dataset: 'sqlite' }));

    expect(screen.getByTestId('run-dataset')).toHaveTextContent(/demo data/i);
  });

  it('warns about unadjusted corporate actions in the window', () => {
    renderResults(
      makeRun({
        corporate_actions: [
          {
            instrument_id: 1,
            symbol: 'AAPL.US',
            ex_date: '2020-08-31',
            action_type: 'split',
            split_ratio: 4,
            dividend: null,
          },
        ],
      }),
    );

    const warning = screen.getByTestId('run-corporate-actions');
    // A correctness warning, not a footnote: signals near an ex-date may be
    // artefacts of the unadjusted split rather than market moves.
    expect(warning).toHaveAttribute('role', 'alert');
    expect(warning).toHaveTextContent(/AAPL\.US/);
    expect(warning).toHaveTextContent(/2020-08-31/);
  });

  it('says nothing about corporate actions when there are none', () => {
    renderResults(makeRun());

    expect(screen.getByTestId('run-coverage')).toBeInTheDocument();
    expect(screen.queryByTestId('run-corporate-actions')).not.toBeInTheDocument();
  });

  it('marks a run recorded against another dataset as not reproducible', () => {
    renderResults(makeRun({ re_runnable: false }));

    expect(screen.getByTestId('run-not-rerunnable')).toHaveTextContent(/not reproducible/i);
  });

  it('marks a run whose model left the registry as unavailable', () => {
    renderResults(makeRun({ model_available: false }));

    expect(screen.getByTestId('run-model-unavailable')).toHaveTextContent(/model unavailable/i);
  });
});

describe('run store', () => {
  it('a run started from the form becomes the shared selected run', async () => {
    // The store is the handoff between destinations: what Research creates,
    // Strategies already has.
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.getRunPerformance).mockResolvedValue({
      run_id: 'run-1',
      initial_capital: 100_000,
      equity: [],
      benchmark: [],
      metrics: {
        total_return: 0.12,
        sharpe_ratio: null,
        max_drawdown: -0.07,
        win_rate: null,
        trade_count: 0,
        winning_trades: 0,
        losing_trades: 0,
      },
      trades: [],
      assumptions: [],
    });
    const user = userEvent.setup();

    renderWorkbench(<Harness results />);

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(await screen.findByRole('button', { name: /run strategy/i }));

    expect(await screen.findByTestId('run-results')).toBeInTheDocument();
    expect(screen.getByTestId('run-coverage')).toBeInTheDocument();
  });
});
