import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import type { Instrument } from '../../src/api/client';
import type { StrategySpec } from '../../src/api/types';
import { RunsProvider } from '../../src/runs/RunsContext';
import { StrategyBuilder } from '../../src/strategies/StrategyBuilder';
import {
  canFillRole,
  componentFor,
  describeStrategy,
  emptyDraft,
  roleRefusal,
} from '../../src/strategies/strategyModel';
import { adxFilter, catalog, macdCrossover, rsiThreshold, templates } from './fixtures';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listModels: vi.fn(),
    listRuns: vi.fn(),
    listStrategies: vi.fn(),
    listStrategyTemplates: vi.fn(),
    createStrategy: vi.fn(),
    replaceStrategy: vi.fn(),
    deleteStrategy: vi.fn(),
    createStrategyRun: vi.fn(),
    getRun: vi.fn(),
    getPrices: vi.fn(),
  };
});

const instruments = [
  { symbol: 'ZZTRND', name: 'Trend Co', currency: 'USD', regime_profile: 'trending' },
  { symbol: 'ZZMEAN', name: 'Mean Co', currency: 'USD', regime_profile: 'mean_reverting' },
] as unknown as Instrument[];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listModels).mockResolvedValue({ total: catalog.length, items: catalog });
  vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listStrategies).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listStrategyTemplates).mockResolvedValue({
    total: templates.length,
    items: templates,
  });
  vi.mocked(apiClient.getPrices).mockResolvedValue({
    total: 1,
    items: [
      { symbol: 'ZZTRND', date: '2024-12-31', open: 10, high: 11, low: 9, close: 10.5, volume: 1 },
    ],
  });
});

async function openBuilder() {
  const person = userEvent.setup();
  render(
    <RunsProvider>
      <StrategyBuilder instruments={instruments} />
    </RunsProvider>,
  );
  await screen.findByTestId('signal-catalogue');
  return person;
}

function addFrom(name: string, role: 'Entry' | 'Exit' | 'Filter') {
  const card = screen.getByTestId(`signal-card-${name}`);
  return within(card).getByRole('button', { name: role });
}

// --- The pure core ---------------------------------------------------------

describe('role enforcement', () => {
  it('reads what a rule advertises rather than assuming every rule can do everything', () => {
    expect(canFillRole(rsiThreshold, 'entry')).toBe(true);
    expect(canFillRole(adxFilter, 'filter')).toBe(true);
    expect(canFillRole(adxFilter, 'entry')).toBe(false);
    expect(canFillRole(adxFilter, 'exit')).toBe(false);
  });

  it('explains a filter-only rule in terms of what it is, not what it lacks', () => {
    const refusal = roleRefusal(adxFilter, 'entry');

    expect(refusal).toMatch(/market state/i);
    expect(refusal).toMatch(/cannot open a position/i);
    expect(refusal).toMatch(/add it as a filter/i);
    // A role the rule does support is never refused.
    expect(roleRefusal(adxFilter, 'filter')).toBeNull();
  });
});

describe('the plain-English summary', () => {
  const draftWith = (...components: ReturnType<typeof componentFor>[]) => ({
    ...emptyDraft('Test'),
    components,
  });

  it('says so plainly when nothing can open a position yet', () => {
    expect(describeStrategy(emptyDraft(), catalog)).toMatch(/nothing opens a position yet/i);
  });

  it('names the entry, its parameters, and the filter that gates it', () => {
    const draft = draftWith(componentFor(rsiThreshold, 'entry'), componentFor(adxFilter, 'filter'));

    const sentence = describeStrategy(draft, catalog);

    expect(sentence).toMatch(
      /Enter when RSI crossing out of its oversold band \(period 14, oversold 30\)/,
    );
    expect(sentence).toMatch(/while ADX above its threshold.*holds/);
    expect(sentence).toMatch(/Long only/);
  });

  it('spells out the combination rule when there is more than one entry', () => {
    const draft = {
      ...draftWith(componentFor(rsiThreshold, 'entry'), componentFor(macdCrossover, 'entry')),
      entry_logic: 'any' as const,
    };

    expect(describeStrategy(draft, catalog)).toMatch(/Enter when ANY of .* or .* fires/);
  });

  it('reads the weighted case as weights, because that is what will be evaluated', () => {
    const entry = { ...componentFor(rsiThreshold, 'entry'), weight: 2 };
    const draft = {
      ...draftWith(entry, componentFor(macdCrossover, 'entry')),
      entry_logic: 'weighted' as const,
      entry_threshold: 1.5,
    };

    const sentence = describeStrategy(draft, catalog);

    expect(sentence).toMatch(/worth 1\.5 or more in total/);
    expect(sentence).toMatch(/×2/);
  });

  it('turns the execution criteria into the exit half of the sentence', () => {
    const draft = {
      ...draftWith(componentFor(rsiThreshold, 'entry')),
      execution: {
        ...emptyDraft().execution,
        stop_loss_pct: 0.05,
        take_profit_pct: 0.1,
        allow_shorts: true,
      },
    };

    const sentence = describeStrategy(draft, catalog);

    expect(sentence).toMatch(/Exit on a 5% stop or a 10% target/);
    expect(sentence).toMatch(/bearish entry opens a short/i);
  });

  it('states the agreement window only when it is wider than one bar', () => {
    const base = draftWith(componentFor(rsiThreshold, 'entry'));

    expect(describeStrategy(base, catalog)).not.toMatch(/bars of each other/);
    expect(describeStrategy({ ...base, combine_window_days: 3 }, catalog)).toMatch(
      /within 3 bars of each other/,
    );
  });
});

// --- The screen ------------------------------------------------------------

describe('StrategyBuilder', () => {
  it('groups the catalogue by the category the registry reports', async () => {
    await openBuilder();

    expect(screen.getByRole('region', { name: 'Mean reversion' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Momentum' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Trend' })).toBeInTheDocument();
  });

  it('refuses a filter-only rule as an entry and says why, instead of going quiet', async () => {
    const person = await openBuilder();

    await person.click(addFrom('adx-trend-filter', 'Entry'));

    const refusal = await screen.findByTestId('role-refusal-adx-trend-filter');
    expect(refusal).toHaveAttribute('role', 'alert');
    expect(refusal).toHaveTextContent(/cannot open a position/i);
    // Nothing was added: the strategy is still empty.
    expect(screen.getByTestId('builder-no-components')).toBeInTheDocument();
  });

  it('marks the unsupported role as unavailable on the control itself', async () => {
    await openBuilder();

    const card = screen.getByTestId('signal-card-adx-trend-filter');
    expect(within(card).getByRole('button', { name: 'Entry' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    // Still focusable and still clickable — that is how the refusal gets said.
    expect(within(card).getByRole('button', { name: 'Entry' })).toBeEnabled();
    expect(within(card).getByRole('button', { name: 'Filter' })).not.toHaveAttribute(
      'aria-disabled',
    );
  });

  it('accepts the same rule in the role it does advertise', async () => {
    const person = await openBuilder();

    await person.click(addFrom('adx-trend-filter', 'Filter'));

    expect(screen.getByTestId('component-adx-trend-filter-filter')).toBeInTheDocument();
    expect(screen.queryByTestId('builder-no-components')).not.toBeInTheDocument();
  });

  it('rewrites the plain-English summary as the strategy is assembled', async () => {
    const person = await openBuilder();

    expect(screen.getByTestId('strategy-summary')).toHaveTextContent(
      /nothing opens a position yet/i,
    );

    await person.click(addFrom('rsi-threshold', 'Entry'));
    expect(screen.getByTestId('strategy-summary')).toHaveTextContent(
      /Enter when RSI crossing out of its oversold band \(period 14, oversold 30\)/,
    );

    await person.click(addFrom('adx-trend-filter', 'Filter'));
    expect(screen.getByTestId('strategy-summary')).toHaveTextContent(/while ADX above/);

    // And it follows a parameter edit, not just the component list.
    const period = screen.getByLabelText('period for rsi-threshold');
    await person.clear(period);
    await person.type(period, '7');
    expect(screen.getByTestId('strategy-summary')).toHaveTextContent(/period 7/);
  });

  it('warns about a strategy with no exit rather than blocking it', async () => {
    const person = await openBuilder();

    await person.click(addFrom('rsi-threshold', 'Entry'));

    const warnings = screen.getByTestId('strategy-warnings');
    expect(warnings).toHaveTextContent(/no exit signal/i);
    // Warned, not blocked: §3 says this shape is legal.
    expect(screen.getByRole('button', { name: /save strategy/i })).toBeEnabled();
  });

  it('shows per-component weights only once the logic is weighted', async () => {
    const person = await openBuilder();
    await person.click(addFrom('rsi-threshold', 'Entry'));

    expect(screen.queryByLabelText(/weight for rsi-threshold/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/entry threshold/i)).not.toBeInTheDocument();

    await person.selectOptions(screen.getByLabelText(/entry logic/i), 'weighted');

    expect(screen.getByLabelText(/weight for rsi-threshold/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/entry threshold/i)).toBeInTheDocument();
  });

  it('offers the templates the server serves, not a list of its own', async () => {
    await openBuilder();

    const list = await screen.findByTestId('template-list');
    expect(apiClient.listStrategyTemplates).toHaveBeenCalledTimes(1);
    // Server order, server names, server prose.
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((row) => row.textContent?.slice(0, 20)),
    ).toEqual([
      expect.stringContaining('RSI mean reversion'),
      expect.stringContaining('MACD trend'),
      expect.stringContaining('Donchian'),
      expect.stringContaining('Dual-confirmation'),
    ]);
  });

  it('loads a template into the builder as a working, unsaved strategy', async () => {
    const person = await openBuilder();
    await screen.findByTestId('template-list');

    await person.click(
      screen.getByRole('button', { name: /load the rsi mean reversion template/i }),
    );

    expect(screen.getByDisplayValue('RSI mean reversion')).toBeInTheDocument();
    expect(screen.getByTestId('strategy-summary')).toHaveTextContent(/Enter when RSI/);
    // The template's own execution criteria came with it.
    expect(screen.getByTestId('strategy-summary')).toHaveTextContent(/8% stop/);
    expect(screen.getByLabelText(/stop loss/i)).toHaveValue(8);
    // Loading a template starts something unsaved: the first Save must create,
    // never replace the template it came from.
    expect(screen.getByRole('button', { name: /save strategy/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save as copy/i })).not.toBeInTheDocument();
  });

  it('keeps a template honest against a registry that lacks its rules', async () => {
    vi.mocked(apiClient.listModels).mockResolvedValue({ total: 1, items: [rsiThreshold] });
    const person = await openBuilder();
    await screen.findByTestId('template-list');

    // Donchian and volume-spike are not registered in this deployment.
    await person.click(screen.getByRole('button', { name: /load the donchian breakout/i }));

    expect(screen.getByTestId('builder-notice')).toHaveTextContent(/donchian-breakout/);
    expect(screen.getByTestId('builder-notice')).toHaveTextContent(/volume-spike/);
    expect(screen.getByTestId('builder-notice')).toHaveTextContent(/does not register/i);
    // The rest of the template did not load a component pointing at a rule
    // that would be rejected on save.
    expect(screen.queryByTestId('component-donchian-breakout-entry')).not.toBeInTheDocument();
  });

  it('explains templates that could not be loaded, and offers a retry', async () => {
    vi.mocked(apiClient.listStrategyTemplates).mockRejectedValue(
      new apiClient.ApiError(0, 'Backend unreachable'),
    );
    await openBuilder();

    const error = await screen.findByTestId('templates-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(within(error).getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('saves the spec it is showing, with roles and coerced parameters', async () => {
    vi.mocked(apiClient.createStrategy).mockImplementation(async (spec) => ({
      ...spec,
      id: 'strategy-1',
      owner_id: 'user-1',
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
    }));
    const person = await openBuilder();

    await person.click(addFrom('rsi-threshold', 'Entry'));
    await person.click(addFrom('adx-trend-filter', 'Filter'));
    const name = screen.getByLabelText('Name');
    await person.clear(name);
    await person.type(name, 'Oversold in an uptrend');
    await person.click(screen.getByRole('button', { name: /save strategy/i }));

    await waitFor(() => expect(apiClient.createStrategy).toHaveBeenCalledTimes(1));
    const spec = vi.mocked(apiClient.createStrategy).mock.calls[0][0] as StrategySpec;
    expect(spec.name).toBe('Oversold in an uptrend');
    expect(spec.components.map((component) => [component.rule_name, component.role])).toEqual([
      ['rsi-threshold', 'entry'],
      ['adx-trend-filter', 'filter'],
    ]);
    // Strings in the form, numbers on the wire — coerced through paramSpec.
    expect(spec.components[0].parameters).toEqual({ period: 14, oversold: 30 });
    expect(spec.entry_logic).toBe('all');
  });

  it('runs the strategy that is on screen, not the last one that was saved', async () => {
    vi.mocked(apiClient.createStrategyRun).mockRejectedValue(
      new apiClient.ApiError(0, 'no backend'),
    );
    const person = await openBuilder();

    await person.click(addFrom('rsi-threshold', 'Entry'));
    expect(screen.getByRole('button', { name: /run backtest/i })).toBeDisabled();

    await person.type(screen.getByLabelText(/add tickers/i), 'ZZTRND{Enter}');
    await person.click(screen.getByRole('button', { name: /run backtest/i }));

    await waitFor(() => expect(apiClient.createStrategyRun).toHaveBeenCalledTimes(1));
    const body = vi.mocked(apiClient.createStrategyRun).mock.calls[0][0];
    expect(body.symbols).toEqual(['ZZTRND']);
    expect(body.strategy_id).toBeUndefined();
    expect(body.strategy?.components).toHaveLength(1);
    // A failure to reach the backend is an explained state, never a blank one.
    expect(await screen.findByTestId('builder-run-error')).toHaveAttribute('role', 'alert');
  });

  it('adds a handed-over signal as the first entry, with its ticker as the universe', async () => {
    render(
      <RunsProvider>
        <StrategyBuilder
          instruments={instruments}
          seed={{ key: 'k', model: 'rsi-threshold', values: { period: '21' }, symbols: ['ZZMEAN'] }}
        />
      </RunsProvider>,
    );
    await screen.findByTestId('signal-catalogue');

    expect(await screen.findByText(/rsi-threshold added as entry/i)).toBeInTheDocument();
    expect(screen.getByTestId('universe-count')).toHaveTextContent(/1 ticker/i);
    expect(
      within(screen.getByRole('list', { name: /selected tickers/i })).getByText('ZZMEAN'),
    ).toBeInTheDocument();
  });

  it('distinguishes an empty library from one it could not read', async () => {
    await openBuilder();
    expect(screen.getByTestId('library-empty')).toHaveTextContent(/nothing saved yet/i);
  });

  it('explains a library that could not be loaded, and offers a retry', async () => {
    vi.mocked(apiClient.listStrategies).mockRejectedValue(
      new apiClient.ApiError(0, 'Backend unreachable'),
    );
    await openBuilder();

    const error = await screen.findByTestId('library-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(within(error).getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });
});
