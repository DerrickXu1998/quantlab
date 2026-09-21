import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import * as rulesApi from '../../src/quantlab/data/customRules';
import { StrategyLabView } from '../../src/quantlab/views/StrategyLabView';
import { RunsProvider } from '../../src/runs/RunsContext';
import { installResizeObserver } from '../mocks/resize-observer';
import { makePerformance, makeRun, model as builtinModel } from './fixtures';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listModels: vi.fn(),
    listRuns: vi.fn(),
    getPrices: vi.fn(),
    createRun: vi.fn(),
    getRun: vi.fn(),
    getRunPerformance: vi.fn(),
  };
});

vi.mock('../../src/quantlab/data/customRules', async (importOriginal) => {
  const actual = await importOriginal<typeof rulesApi>();
  return {
    ...actual,
    listSignalTemplates: vi.fn(),
    listCustomRules: vi.fn(),
    createCustomRule: vi.fn(),
    updateCustomRule: vi.fn(),
    deleteCustomRule: vi.fn(),
  };
});

installResizeObserver();

const instruments = [
  {
    symbol: 'ZZTRND',
    name: 'Trend Co',
    currency: 'USD',
    kind: 'equity',
    regime_profile: 'trending',
  },
] as unknown as apiClient.Instrument[];

const customModel: apiClient.Model = {
  name: 'rsi-recovery',
  version: '1.0.0',
  lookback_days: 16,
  scale_class: 'scale_free',
  direction_semantics: 'config-defined: comparator plus bullish_on fix the direction',
  origin: 'custom',
  custom_rule_id: 'rule-1',
  template: 'indicator-threshold',
  parameters: [],
};

const rule: rulesApi.CustomRule = {
  rule_id: 'rule-1',
  name: 'rsi-recovery',
  slug: 'rsi-recovery',
  template: 'indicator-threshold',
  config: {
    input: { source: 'indicator', indicator: 'rsi', params: { period: 14 } },
    transform: 'raw',
    comparator: 'crosses_above',
    threshold: 30,
    bullish_on: 'above',
  },
  lookback_days: 16,
  created_at: '2026-09-20T10:00:00Z',
  updated_at: '2026-09-20T10:00:00Z',
};

const thresholdTemplate: rulesApi.SignalTemplate = {
  id: 'indicator-threshold',
  version: '1.0.0',
  description: 'Fire when a series crosses a fixed threshold.',
  inputs: 'bars',
  available_on_dataset: true,
  config_fields: {
    input: {
      sources: ['close', 'indicator'],
      indicators: ['sma', 'ema', 'rsi', 'rolling_std', 'rolling_max', 'rolling_min'],
    },
    transform: { choices: ['raw', 'pct_change'], default: 'raw' },
    transform_window: { type: 'int', default: 1, minimum: 1, maximum: 63 },
    comparator: { choices: ['crosses_above', 'crosses_below', 'enters_zone', 'exits_zone'] },
    threshold: { type: 'float' },
    bullish_on: { choices: ['above', 'below'], default: 'above' },
  },
};

const crossoverTemplate: rulesApi.SignalTemplate = {
  id: 'indicator-crossover',
  version: '1.0.0',
  description: 'Fire when operand A crosses operand B.',
  inputs: 'bars',
  available_on_dataset: true,
  config_fields: {
    a: { operands: ['close', 'sma', 'ema', 'rsi', 'macd_line'] },
    b: { operands: ['close', 'sma', 'ema', 'rsi', 'macd_line'] },
  },
};

function renderLab(hash = '#/strategies') {
  window.location.hash = hash;
  return render(
    <RunsProvider>
      <StrategyLabView instruments={instruments} />
    </RunsProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = '';
  vi.mocked(apiClient.listModels).mockResolvedValue({
    total: 2,
    items: [builtinModel, customModel],
  });
  vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.getPrices).mockResolvedValue({
    total: 1,
    items: [
      {
        symbol: 'ZZTRND',
        date: '2024-12-31',
        open: 10,
        high: 11,
        low: 9,
        close: 10.5,
        volume: 100,
      },
    ],
  });
  vi.mocked(apiClient.getRunPerformance).mockResolvedValue(makePerformance());
  vi.mocked(rulesApi.listCustomRules).mockResolvedValue({ total: 1, items: [rule] });
  vi.mocked(rulesApi.listSignalTemplates).mockResolvedValue({
    total: 2,
    items: [thresholdTemplate, crossoverTemplate],
  });
});

describe('Strategy rail grouping', () => {
  it('separates builtins from My rules, with a generated summary per rule', async () => {
    renderLab();

    const builtin = await screen.findByTestId('model-group-builtin');
    expect(within(builtin).getByText('sma-crossover')).toBeInTheDocument();

    const custom = screen.getByTestId('model-group-custom');
    expect(within(custom).getByText('rsi-recovery')).toBeInTheDocument();
    // The summary sentence is generated from the rule's own config, not from
    // the template-level semantics string the catalog carries.
    expect(within(custom).getByTestId('fires-on-rsi-recovery')).toHaveTextContent(
      'Bullish when 14-day RSI crosses above 30.',
    );
  });
});

describe('Rule builder', () => {
  async function openBuilder(user: ReturnType<typeof userEvent.setup>) {
    renderLab();
    await screen.findByTestId('model-group-custom');
    await user.click(screen.getByRole('button', { name: /new rule/i }));
    return screen.findByTestId('rule-builder');
  }

  it('renders the template picker from the catalog and generates the config form', async () => {
    const user = userEvent.setup();
    const builder = await openBuilder(user);

    const picker = within(builder).getByLabelText(/template/i);
    expect(within(picker).getByRole('option', { name: /indicator-threshold/ })).toBeInTheDocument();
    expect(within(picker).getByRole('option', { name: /indicator-crossover/ })).toBeInTheDocument();

    await user.selectOptions(picker, 'indicator-threshold');

    const config = await within(builder).findByTestId('rule-config');
    expect(within(config).getByLabelText(/comparator/i)).toBeInTheDocument();
    expect(within(config).getByLabelText(/threshold/i)).toBeInTheDocument();
    expect(within(config).getByLabelText(/bullish_on/i)).toBeInTheDocument();
    // transform_window is hidden until pct_change asks for it.
    expect(within(config).queryByLabelText(/transform_window/i)).not.toBeInTheDocument();
  });

  it('shows indicator params only for an indicator input, and validates them', async () => {
    const user = userEvent.setup();
    const builder = await openBuilder(user);
    await user.selectOptions(within(builder).getByLabelText(/template/i), 'indicator-threshold');
    const config = await within(builder).findByTestId('rule-config');

    // The default input is the close: no indicator machinery on screen.
    expect(within(config).queryByLabelText(/^indicator$/i)).not.toBeInTheDocument();

    await user.selectOptions(within(config).getByLabelText(/input source/i), 'indicator');
    await user.selectOptions(within(config).getByLabelText(/^indicator$/i), 'rsi');

    const period = within(config).getByLabelText(/period/i) as HTMLInputElement;
    expect(period.value).toBe('14');

    await user.clear(period);
    await user.type(period, '1');
    // The alert names its own field (an untouched threshold alerts separately).
    expect(await screen.findByText(/period: must be >= 2/)).toBeInTheDocument();
    expect(period).toHaveAttribute('aria-invalid', 'true');
    expect(within(builder).getByRole('button', { name: /save rule/i })).toBeDisabled();
  });

  it('updates the plain-English preview as the config changes', async () => {
    const user = userEvent.setup();
    const builder = await openBuilder(user);
    await user.selectOptions(within(builder).getByLabelText(/template/i), 'indicator-threshold');
    const config = await within(builder).findByTestId('rule-config');

    await user.selectOptions(within(config).getByLabelText(/input source/i), 'indicator');
    await user.selectOptions(within(config).getByLabelText(/^indicator$/i), 'rsi');
    await user.type(within(config).getByLabelText(/threshold/i), '30');

    expect(within(builder).getByTestId('rule-preview')).toHaveTextContent(
      'Bullish when 14-day RSI crosses above 30.',
    );
  });

  it('saves the rule with the config the form state implies, and lists it under My rules', async () => {
    const newRule: rulesApi.CustomRule = {
      ...rule,
      rule_id: 'rule-2',
      name: 'RSI recovery',
      slug: 'rsi-recovery-2',
    };
    const newModel: apiClient.Model = {
      ...customModel,
      name: 'RSI recovery',
      custom_rule_id: 'rule-2',
    };
    vi.mocked(rulesApi.createCustomRule).mockResolvedValue(newRule);
    vi.mocked(apiClient.listModels)
      .mockResolvedValueOnce({ total: 2, items: [builtinModel, customModel] })
      .mockResolvedValue({ total: 3, items: [builtinModel, customModel, newModel] });
    vi.mocked(rulesApi.listCustomRules)
      .mockResolvedValueOnce({ total: 1, items: [rule] })
      .mockResolvedValue({ total: 2, items: [rule, newRule] });

    const user = userEvent.setup();
    const builder = await openBuilder(user);
    await user.selectOptions(within(builder).getByLabelText(/template/i), 'indicator-threshold');
    const config = await within(builder).findByTestId('rule-config');
    await user.selectOptions(within(config).getByLabelText(/input source/i), 'indicator');
    await user.selectOptions(within(config).getByLabelText(/^indicator$/i), 'rsi');
    await user.type(within(config).getByLabelText(/threshold/i), '30');
    await user.type(within(builder).getByLabelText(/name/i), 'RSI recovery');
    await user.click(within(builder).getByRole('button', { name: /save rule/i }));

    await waitFor(() => expect(rulesApi.createCustomRule).toHaveBeenCalled());
    expect(rulesApi.createCustomRule).toHaveBeenCalledWith({
      name: 'RSI recovery',
      template: 'indicator-threshold',
      config: {
        input: { source: 'indicator', indicator: 'rsi', params: { period: 14 } },
        transform: 'raw',
        transform_window: 1,
        comparator: 'crosses_above',
        threshold: 30,
        bullish_on: 'above',
      },
    });

    // The reloaded catalog lists the new rule under My rules, selected.
    const custom = await screen.findByTestId('model-group-custom');
    expect(await within(custom).findByText('RSI recovery')).toBeInTheDocument();
    expect(
      await screen.findByRole('region', { name: /RSI recovery — strategy run/i }),
    ).toBeInTheDocument();
  });

  it('edits an existing rule: config prefilled, template locked, PATCH on save', async () => {
    vi.mocked(rulesApi.updateCustomRule).mockResolvedValue({
      ...rule,
      config: { ...rule.config, threshold: 25 },
    });
    const user = userEvent.setup();
    renderLab();
    const custom = await screen.findByTestId('model-group-custom');

    await user.click(within(custom).getByRole('button', { name: /edit rule rsi-recovery/i }));

    const builder = await screen.findByTestId('rule-builder');
    expect(within(builder).getByLabelText(/template/i)).toBeDisabled();
    expect((within(builder).getByLabelText(/name/i) as HTMLInputElement).value).toBe(
      'rsi-recovery',
    );
    expect((await within(builder).findByLabelText(/threshold/i)) as HTMLInputElement).toHaveValue(
      30,
    );
    // The prefill restores the indicator input and its period.
    expect(within(builder).getByLabelText(/^indicator$/i)).toHaveValue('rsi');
    expect(within(builder).getByTestId('rule-preview')).toHaveTextContent(
      'Bullish when 14-day RSI crosses above 30.',
    );

    const threshold = within(builder).getByLabelText(/threshold/i);
    await user.clear(threshold);
    await user.type(threshold, '25');
    await user.click(within(builder).getByRole('button', { name: /save changes/i }));

    await waitFor(() => expect(rulesApi.updateCustomRule).toHaveBeenCalled());
    const [ruleId, body] = vi.mocked(rulesApi.updateCustomRule).mock.calls[0];
    expect(ruleId).toBe('rule-1');
    expect(body).toMatchObject({ name: 'rsi-recovery', config: { threshold: 25 } });
  });

  it('turns a template-catalog failure into an error with a retry', async () => {
    vi.mocked(rulesApi.listSignalTemplates)
      .mockRejectedValueOnce(new apiClient.ApiError(500, 'boom'))
      .mockResolvedValue({ total: 2, items: [thresholdTemplate, crossoverTemplate] });
    const user = userEvent.setup();
    renderLab();
    await screen.findByTestId('model-group-custom');
    await user.click(screen.getByRole('button', { name: /new rule/i }));

    const error = await screen.findByTestId('rule-templates-error');
    expect(error).toHaveAttribute('role', 'alert');

    await user.click(within(error).getByRole('button', { name: /retry/i }));
    expect(await screen.findByLabelText(/template/i)).toBeInTheDocument();
  });
});

describe('Custom rule runs', () => {
  it('shows no signal-parameters section and submits custom_rule_id', async () => {
    vi.mocked(apiClient.createRun).mockResolvedValue(makeRun());
    vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());
    const user = userEvent.setup();
    renderLab();

    const custom = await screen.findByTestId('model-group-custom');
    await user.click(within(custom).getByText('rsi-recovery'));

    const form = await screen.findByTestId('run-config');
    expect(within(form).queryByText('Parameters')).not.toBeInTheDocument();
    expect(form).toHaveTextContent(/baked into its saved config/i);
    // The execution fieldset stays: criteria are per-run, not per-rule.
    expect(screen.getByTestId('execution-fieldset')).toBeInTheDocument();

    await user.selectOptions(await screen.findByLabelText('Instruments'), 'ZZTRND');
    await user.click(screen.getByRole('button', { name: /run strategy/i }));

    await waitFor(() => expect(apiClient.createRun).toHaveBeenCalled());
    const [body] = vi.mocked(apiClient.createRun).mock.calls[0];
    expect(body.custom_rule_id).toBe('rule-1');
    expect(body.model_name).toBeUndefined();
    expect(body.parameters).toBeUndefined();
  });

  it('selects a rule from the ?rule= handoff', async () => {
    renderLab('#/strategies?rule=rule-1');

    expect(
      await screen.findByRole('region', { name: /rsi-recovery — strategy run/i }),
    ).toBeInTheDocument();
    expect(await screen.findByTestId('run-config')).toBeInTheDocument();
  });
});

describe('Rule deletion', () => {
  it('deletes behind a two-step confirm and reloads the rail', async () => {
    vi.mocked(rulesApi.deleteCustomRule).mockResolvedValue(undefined);
    vi.mocked(apiClient.listModels)
      .mockResolvedValueOnce({ total: 2, items: [builtinModel, customModel] })
      .mockResolvedValue({ total: 1, items: [builtinModel] });
    vi.mocked(rulesApi.listCustomRules)
      .mockResolvedValueOnce({ total: 1, items: [rule] })
      .mockResolvedValue({ total: 0, items: [] });
    const user = userEvent.setup();
    renderLab();
    const custom = await screen.findByTestId('model-group-custom');

    await user.click(within(custom).getByRole('button', { name: /delete rule rsi-recovery/i }));
    // Armed, not fired.
    expect(rulesApi.deleteCustomRule).not.toHaveBeenCalled();

    await user.click(within(custom).getByRole('button', { name: /confirm/i }));

    await waitFor(() => expect(rulesApi.deleteCustomRule).toHaveBeenCalledWith('rule-1'));
    await waitFor(() => expect(within(custom).queryByText('rsi-recovery')).not.toBeInTheDocument());
  });
});
