import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../src/api/client';
import { ModelCatalog } from '../src/workbench/ModelCatalog';
import { RunConfig } from '../src/workbench/RunConfig';
import { RunResults } from '../src/workbench/RunResults';
import { WorkbenchProvider } from '../src/workbench/WorkbenchContext';
import { WorkspaceProvider } from '../src/workspace/WorkspaceContext';
import { makeInstrument } from './fixtures';

vi.mock('../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listModels: vi.fn(),
    listInstruments: vi.fn(),
    listSignals: vi.fn(),
    getPrices: vi.fn(),
    createRun: vi.fn(),
    getRun: vi.fn(),
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

function renderWorkbench(ui: React.ReactNode) {
  return render(
    <WorkspaceProvider>
      <WorkbenchProvider>{ui}</WorkbenchProvider>
    </WorkspaceProvider>,
  );
}

beforeEach(() => {
  vi.mocked(apiClient.listModels).mockResolvedValue({ total: 1, items: [inventedModel] });
  vi.mocked(apiClient.listInstruments).mockResolvedValue({
    total: 1,
    items: [makeInstrument()],
  });
  vi.mocked(apiClient.listSignals).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.getPrices).mockResolvedValue({ total: 0, items: [] });
});

describe('ModelCatalog', () => {
  it('lists whatever the backend registry reports, including unknown models', async () => {
    renderWorkbench(<ModelCatalog />);

    expect(await screen.findByText('zeta-reversion')).toBeInTheDocument();
    expect(screen.getByText('v2.1.0')).toBeInTheDocument();
    expect(screen.getByText(/1 parameter/)).toBeInTheDocument();
  });
});

describe('RunConfig', () => {
  it('generates the parameter form from declared metadata', async () => {
    renderWorkbench(<RunConfig />);

    const field = (await screen.findByLabelText(/zeta_threshold/i)) as HTMLInputElement;
    expect(field.value).toBe('12'); // seeded from the declared default
    expect(field.min).toBe('2');
    expect(field.max).toBe('40');
  });

  it('reports an out-of-range value against that specific parameter', async () => {
    const user = userEvent.setup();
    renderWorkbench(<RunConfig />);

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

    renderWorkbench(<RunConfig />);

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /^run$/i }));

    await waitFor(() => expect(apiClient.createRun).toHaveBeenCalled());
    const [body] = vi.mocked(apiClient.createRun).mock.calls[0];
    expect(body.model_name).toBe('zeta-reversion');
    expect(body.symbols).toEqual(['ZZTRND']);
    // The default was not modified, so it is not sent as an override.
    expect(body.parameters).toEqual({});
  });
});

describe('RunResults', () => {
  it('always shows coverage alongside the signal count', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());
    const user = userEvent.setup();

    renderWorkbench(
      <>
        <RunConfig />
        <RunResults />
      </>,
    );

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /^run$/i }));

    const coverage = await screen.findByTestId('run-coverage');
    expect(within(coverage).getByTestId('signal-count')).toHaveTextContent('1');
    // The denominator is never omitted: 2 of 3 had data, 1 of 3 had warm-up.
    expect(coverage).toHaveTextContent('2/3');
    expect(coverage).toHaveTextContent('1/3');
  });

  it('renders a zero-signal run as a result, not a failure', async () => {
    const empty = makeRun({ signal_count: 0, signals: [] });
    vi.mocked(apiClient.createRun).mockResolvedValue(empty);
    vi.mocked(apiClient.getRun).mockResolvedValue(empty);
    const user = userEvent.setup();

    renderWorkbench(
      <>
        <RunConfig />
        <RunResults />
      </>,
    );

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /^run$/i }));

    const empties = await screen.findByTestId('run-empty');
    expect(empties).toHaveTextContent(/no signals/i);
    // Decisively: not an error treatment, and no failure state.
    expect(screen.queryByTestId('run-failed')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    // Coverage is still reported for an empty result.
    expect(screen.getByTestId('run-coverage')).toBeInTheDocument();
  });

  it('renders a failed run distinctly from an empty one', async () => {
    const failed = makeRun({
      status: 'failed',
      error: 'something broke',
      signal_count: 0,
      signals: [],
    });
    vi.mocked(apiClient.createRun).mockResolvedValue(failed);
    vi.mocked(apiClient.getRun).mockResolvedValue(failed);
    const user = userEvent.setup();

    renderWorkbench(
      <>
        <RunConfig />
        <RunResults />
      </>,
    );

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /^run$/i }));

    expect(await screen.findByTestId('run-failed')).toBeInTheDocument();
    expect(screen.queryByTestId('run-empty')).not.toBeInTheDocument();
  });
});
