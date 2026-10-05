import { render, screen as dom, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../../src/api/client';
import type { ScreenMetricCoverage, ScreenResult } from '../../../src/api/types';
import { SCREEN_METRICS } from '../../../src/api/types';
import { ScreenView } from '../../../src/research/screen/ScreenView';
import { UNIVERSES } from './fixtures';

vi.mock('../../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return { ...actual, screen: vi.fn(), listUniverses: vi.fn() };
});

const listUniverses = vi.mocked(apiClient.listUniverses);
const runScreen = vi.mocked(apiClient.screen);

/**
 * The US list as production holds it: Tiingo's published figures for ~500
 * names, and no SEC-filed concepts, so every computed ratio measures nobody.
 */
const MEASURED: Partial<Record<(typeof SCREEN_METRICS)[number], [number, string]>> = {
  market_cap: [500, 'marketCap'],
  enterprise_value: [500, 'enterpriseVal'],
  pe_ratio: [471, 'peRatio'],
  pb_ratio: [488, 'pbRatio'],
  peg_ratio_1y: [402, 'trailingPEG1Y'],
  roe_reported: [499, 'roe'],
  gross_margin_reported: [499, 'grossMargin'],
  piotroski_f_score: [496, 'piotroskiFScore'],
};

const COVERAGE: ScreenMetricCoverage[] = SCREEN_METRICS.map((metric) => {
  const measured = MEASURED[metric];
  return {
    metric,
    measured: measured ? measured[0] : 0,
    universe: 503,
    requires: measured ? [`tiingo:${measured[1]}`] : ['net_income', 'equity'],
  };
});

const RESULT: ScreenResult = {
  as_of: '2026-10-02',
  universe: 'sp500',
  universe_size: 503,
  rows: [
    {
      symbol: 'AAPL.US',
      name: 'Apple Inc.',
      values: {
        market_cap: 4.901e12,
        pe_ratio: 38.0131,
        pb_ratio: 45.5824,
        peg_ratio_1y: 1.2974,
        roe_reported: 1.3718,
        gross_margin_reported: 0.4718,
        piotroski_f_score: 8,
        pe: null,
        leverage: null,
      },
    },
  ],
  coverage: COVERAGE,
  sort_by: null,
  excluded_by_constraint: 0,
  excluded_unmeasured: 0,
};

async function runOnce() {
  const user = userEvent.setup();
  render(<ScreenView onSelectSymbol={vi.fn()} />);
  await dom.findByLabelText('Universe');
  await user.click(dom.getByTestId('run-screen'));
  await dom.findByTestId('screen-table');
  return user;
}

function headers(): string[] {
  return within(dom.getByTestId('screen-table'))
    .getAllByRole('columnheader')
    .map((cell) => cell.textContent ?? '');
}

beforeEach(() => {
  vi.clearAllMocks();
  listUniverses.mockResolvedValue(UNIVERSES);
  runScreen.mockResolvedValue(RESULT);
});

describe('Screen — Tiingo’s published metrics', () => {
  it('asks for every metric, Tiingo’s included', async () => {
    await runOnce();

    expect(runScreen.mock.calls[0][0].metrics).toEqual([...SCREEN_METRICS]);
  });

  it('shows the columns the answer could measure, not twenty dashes', async () => {
    await runOnce();

    const shown = headers();
    expect(shown).toEqual(expect.arrayContaining(['Market cap', 'P/E (Tiingo)', 'Piotroski F']));
    // Computed from filed concepts, which this list does not have.
    expect(shown.join('|')).not.toMatch(/Leverage/);
  });

  it('renders each figure in its own unit', async () => {
    await runOnce();

    const row = within(dom.getByTestId('screen-table')).getAllByRole('row')[1];
    expect(row).toHaveTextContent('$4.90T');
    expect(row).toHaveTextContent('38.0×');
    expect(row).toHaveTextContent('47.2%'); // gross margin, held as 0.4718
    expect(row).toHaveTextContent('137.2%'); // ROE above 100% is real for Apple
  });

  it('adds a column without re-running the screen', async () => {
    const user = await runOnce();

    await user.click(dom.getByText(/columns \(/i));
    await user.click(dom.getByTestId('column-leverage'));

    expect(headers().join('|')).toMatch(/Leverage/);
    expect(runScreen).toHaveBeenCalledTimes(1);
  });

  it('says in one line which metrics nobody here can be measured on', async () => {
    await runOnce();

    const results = dom.getByTestId('screen-results-panel');
    const line = within(results).getByTestId('coverage-unmeasurable');
    expect(line).toHaveTextContent('P/E, P/B, ROE, Leverage, Net margin, Gross margin, Current ratio');
    expect(line).toHaveTextContent('need net income, shareholders’ equity');
    // No zero-length bars for them, only for what was measured.
    expect(within(results).queryByTestId('coverage-leverage')).toBeNull();
    expect(within(results).getByTestId('coverage-market_cap')).toBeInTheDocument();
  });

  it('starts from eight columns when every Tiingo metric is measured', async () => {
    runScreen.mockResolvedValue({
      ...RESULT,
      coverage: RESULT.coverage.map((entry) =>
        ['pe', 'pb', 'roe', 'leverage', 'net_margin', 'gross_margin', 'current_ratio'].includes(
          entry.metric,
        )
          ? entry
          : { ...entry, measured: 450, requires: [`tiingo:${entry.metric}`] },
      ),
    });
    await runOnce();

    const shown = headers().slice(3); // after #, symbol, name
    expect(shown).toHaveLength(8);
    expect(shown).toEqual(expect.arrayContaining(['Market cap', 'P/E (Tiingo)', 'Debt/equity (Tiingo)']));
    expect(shown.join('|')).not.toMatch(/EPS QoQ/);
  });

  it('names the Tiingo field a metric is read from', async () => {
    await runOnce();

    expect(dom.getByTestId('coverage-pe_ratio')).toHaveTextContent("needs Tiingo's peRatio");
    expect(dom.getByTestId('coverage-pe_ratio')).toHaveTextContent('471 of 503');
  });

  it('starts a new constraint on a metric the answer can measure', async () => {
    const user = await runOnce();

    await user.click(dom.getByRole('button', { name: /add/i }));

    const row = dom.getByTestId('constraint-market_cap');
    expect(within(row).getByLabelText('Metric')).toHaveValue('market_cap');
  });

  it('says a Tiingo margin is a fraction, and echoes the bound as a percentage', async () => {
    const user = await runOnce();

    await user.click(dom.getByRole('button', { name: /add/i }));
    await user.selectOptions(
      within(dom.getByTestId('constraint-market_cap')).getByLabelText('Metric'),
      'gross_margin_reported',
    );
    const row = dom.getByTestId('constraint-gross_margin_reported');
    await user.type(within(row).getByLabelText('Min'), '0.4');

    expect(row).toHaveTextContent('a fraction — 0.12 is 12%');
    expect(row).toHaveTextContent('≥ 40.0%');
  });

  it('constrains and ranks by a Tiingo metric', async () => {
    const user = await runOnce();

    await user.click(dom.getByRole('button', { name: /add/i }));
    await user.selectOptions(
      within(dom.getByTestId('constraint-market_cap')).getByLabelText('Metric'),
      'piotroski_f_score',
    );
    await user.type(
      within(dom.getByTestId('constraint-piotroski_f_score')).getByLabelText('Min'),
      '7',
    );
    await user.click(dom.getByTestId('run-screen'));

    await waitFor(() => expect(runScreen).toHaveBeenCalledTimes(2));
    expect(runScreen.mock.calls[1][0].constraints).toEqual([
      { metric: 'piotroski_f_score', min: 7, max: null },
    ]);
  });
});
