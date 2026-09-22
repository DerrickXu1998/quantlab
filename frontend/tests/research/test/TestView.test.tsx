import { render, screen as dom, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../../src/api/client';
import type { Run } from '../../../src/api/client';
import { TestView } from '../../../src/research/test/TestView';
import { RunsProvider } from '../../../src/runs/RunsContext';
import { CATALOGUE, INSTRUMENTS, LEGACY_RULE, MATERIALISED } from './fixtures';

vi.mock('../../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listModels: vi.fn(),
    listRuns: vi.fn(),
    listInstruments: vi.fn(),
    getPrices: vi.fn(),
  };
});

const listModels = vi.mocked(apiClient.listModels);
const listRuns = vi.mocked(apiClient.listRuns);
const listInstruments = vi.mocked(apiClient.listInstruments);
const getPrices = vi.mocked(apiClient.getPrices);

/** A run against one of the three rules that were ever materialised. */
function makeRun(modelName: string): Run {
  return {
    id: `run-${modelName}`,
    model_name: modelName,
    model_version: '1.0.0',
    parameters: {},
    symbols: ['CAT.US'],
    start_date: '2024-01-01',
    end_date: '2024-12-31',
    status: 'completed',
    signal_count: 12,
    created_at: '2026-09-01T00:00:00Z',
  } as unknown as Run;
}

function renderTest() {
  return render(
    <RunsProvider>
      <TestView />
    </RunsProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listModels.mockResolvedValue({ total: CATALOGUE.length, items: CATALOGUE });
  listRuns.mockResolvedValue({ total: 3, items: MATERIALISED.map(makeRun) as never });
  listInstruments.mockResolvedValue({ total: 2, items: INSTRUMENTS } as never);
  getPrices.mockResolvedValue({ total: 0, items: [] } as never);
});

describe('Test — the catalogue is the registry, not the signals table', () => {
  it('lists every registered rule, including the nineteen with no history', async () => {
    // The defect this replaces: the old panel rendered signal output, so it
    // showed the three rules that had been materialised and was silent about
    // the other nineteen. A user would reasonably conclude the product had
    // three rules.
    renderTest();
    await dom.findByTestId('rule-catalogue');

    for (const rule of CATALOGUE) {
      expect(dom.getByTestId(`rule-${rule.name}`)).toBeInTheDocument();
    }
    expect(dom.getByTestId('rule-census')).toHaveTextContent('22 rules in the registry');
  });

  it('marks a rule with no run history as untried rather than hiding it', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    // Nine fundamental rules among the nineteen — every one of them visible.
    expect(dom.getByTestId('rule-untried-gross-margin-floor')).toHaveTextContent(/no runs yet/i);
    expect(dom.getByTestId('rule-untried-roe-floor')).toBeInTheDocument();
    // And the three that do have history are not marked untried.
    await waitFor(() => expect(dom.queryByTestId('rule-untried-sma-crossover')).toBeNull());
    expect(dom.getByTestId('rule-census')).toHaveTextContent(/19 have never been run here/i);
  });

  it('groups the rules by what they measure, including the fundamentals', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    const fundamentals = dom.getByTestId('rule-group-fundamental');
    expect(within(fundamentals).getByRole('heading')).toHaveTextContent(/fundamentals/i);
    // The nine that read filed accounts.
    expect(within(fundamentals).getAllByRole('button')).toHaveLength(9);
    expect(dom.getByTestId('rule-group-trend')).toBeInTheDocument();
    expect(dom.getByTestId('rule-group-momentum')).toBeInTheDocument();
  });

  it('calls them rules, never models, and says what a rule is', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    // "Model" implies a fitted artifact with weights and invites "trained on
    // what?", which has no answer. These are predicates.
    const heading = dom.getByRole('heading', { name: 'Rules' });
    expect(heading).toBeInTheDocument();
    expect(dom.queryByRole('heading', { name: 'Models' })).toBeNull();
    // The panel cannot be titled without stating what it is.
    expect(heading.parentElement).toHaveTextContent(/not trained models/i);
  });
});

describe('Test — the metadata the old list threw away', () => {
  it('shows each rule’s summary, roles and required concepts', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    const row = dom.getByTestId('rule-gross-margin-floor');
    expect(row).toHaveTextContent('Gross margin above a floor.');
    expect(row).toHaveTextContent(/filter/i);
    // Written the way an analyst says them, not as column names.
    expect(dom.getByTestId('rule-concepts-gross-margin-floor')).toHaveTextContent(
      'Gross profit, Revenue',
    );
  });

  it('explains a role rather than leaving the word unexplained', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    const filter = within(dom.getByTestId('rule-adx-trend-filter')).getByTitle(
      /only permits entries while it is true/i,
    );
    expect(filter).toHaveTextContent(/filter/i);
  });

  it('says plainly when a rule reads no filed accounts at all', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    expect(dom.getByTestId('rule-sma-crossover')).toHaveTextContent(/reads price bars only/i);
  });

  it('survives a backend that predates the metadata, instead of crashing on it', async () => {
    // `model?.requires_facts.length` threw here once: the optional chain
    // guards the model and then dereferences a field the older backend does
    // not send.
    listModels.mockResolvedValue({ total: 1, items: [LEGACY_RULE] });
    renderTest();

    const row = await dom.findByTestId('rule-legacy-rule');
    expect(row).toHaveTextContent(/reads price bars only/i);
    // No category from the server means uncategorised, said out loud.
    expect(dom.getByTestId('rule-group-uncategorised')).toBeInTheDocument();
    // The summary falls back to the direction semantics rather than blank.
    expect(row).toHaveTextContent(/bullish when the legacy rule fires/i);
  });
});

describe('Test — what the mode says it does', () => {
  it('states on the results panel itself what running a test actually does', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    const heading = dom.getByRole('heading', { name: 'What it would have done' });
    const statement = heading.parentElement as HTMLElement;
    expect(statement).toHaveTextContent(/would have produced over stored history/i);
    // The single most consequential claim a trading surface can make.
    expect(statement).toHaveTextContent(/no order is placed, no money moves/i);
  });

  it('opens with a rule selected and its configuration form generated from it', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    // RunsProvider selects the first registered rule so the form is usable
    // immediately, without this UI hardcoding which rule that is.
    expect(await dom.findByTestId('run-config')).toBeInTheDocument();
    expect(dom.getByTestId('test-config-panel')).toHaveTextContent('sma-crossover');
  });

  it('names the concepts a fundamental rule needs before it is run', async () => {
    const user = userEvent.setup();
    renderTest();
    await dom.findByTestId('rule-catalogue');

    await user.click(dom.getByTestId('rule-roe-floor'));

    const panel = dom.getByTestId('test-config-panel');
    expect(panel).toHaveTextContent(/needs net income, shareholders’ equity to have been filed/i);
    expect(panel).toHaveTextContent(/reported as uncovered in the result rather than silently skipped/i);
  });

  it('describes the empty results panel instead of leaving it blank', async () => {
    renderTest();
    await dom.findByTestId('rule-catalogue');

    const empty = dom.getByTestId('test-no-run');
    expect(empty).toHaveTextContent(/no test run yet/i);
    expect(empty).toHaveTextContent(/what the rule would have signalled/i);
  });

  it('filters the catalogue without ever losing sight of the full count', async () => {
    const user = userEvent.setup();
    renderTest();
    await dom.findByTestId('rule-catalogue');

    await user.type(dom.getByLabelText('Filter rules'), 'gross profit');

    // Matched on a required concept, not only on the name.
    expect(dom.getByTestId('rule-gross-margin-floor')).toBeInTheDocument();
    expect(dom.queryByTestId('rule-sma-crossover')).toBeNull();
    expect(dom.getByTestId('rule-census')).toHaveTextContent('22 rules in the registry');
  });
});

describe('Test — the states of the registry read', () => {
  it('says the registry is unreachable rather than showing an empty catalogue', async () => {
    listModels.mockRejectedValue(new Error('down'));
    renderTest();

    const state = await dom.findByTestId('test-registry-error');
    expect(state).toHaveTextContent(/registry is unreachable/i);
    expect(state).toHaveTextContent(/would read as a product with no rules in it/i);
  });

  it('says an empty registry is empty, and why that is not a frontend problem', async () => {
    listModels.mockResolvedValue({ total: 0, items: [] });
    renderTest();

    expect(await dom.findByTestId('rule-catalogue-empty')).toHaveTextContent(
      /register a rule in the backend/i,
    );
  });
});
