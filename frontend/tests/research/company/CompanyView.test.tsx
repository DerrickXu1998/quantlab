import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../../src/api/client';
import CompanyView from '../../../src/research/company/CompanyView';
import { ThemeProvider } from '../../../src/theme/ThemeProvider';
import { makeBar, makeInstrument } from '../../fixtures';
import { makeFact, makeOverview } from './fixtures';

vi.mock('../../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    listInstruments: vi.fn(),
    getCompanyOverview: vi.fn(),
    getPrices: vi.fn(),
    getFundamentals: vi.fn(),
  };
});

const catalogue = [
  makeInstrument({ symbol: 'CAT', name: 'Caterpillar Inc.' }),
  makeInstrument({ symbol: 'DE', name: 'Deere & Company' }),
];

const bars = [
  makeBar({ symbol: 'CAT', date: '2024-06-27', close: 17.68000030517578 }),
  makeBar({ symbol: 'CAT', date: '2024-06-28', close: 18.219999313354492 }),
];

function renderView(symbol: string | null = null) {
  const onSelectSymbol = vi.fn();
  const view = render(
    <ThemeProvider>
      <CompanyView symbol={symbol} onSelectSymbol={onSelectSymbol} />
    </ThemeProvider>,
  );
  return { onSelectSymbol, view };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listInstruments).mockResolvedValue({
    total: catalogue.length,
    items: catalogue,
  });
  vi.mocked(apiClient.getCompanyOverview).mockResolvedValue(makeOverview());
  vi.mocked(apiClient.getPrices).mockResolvedValue({ total: bars.length, items: bars });
  vi.mocked(apiClient.getFundamentals).mockResolvedValue([]);
});

describe('CompanyView, before a name is chosen', () => {
  it('says how the two controls relate, which the mode switcher above does not', async () => {
    // The shell already names the mode and states its purpose. This line is the
    // part specific to the view: both controls form one question, and moving
    // either re-reads everything below.
    renderView(null);
    expect(screen.getByText(/two controls set the question/i)).toBeInTheDocument();
    expect(
      screen.getByText(/the same company on two dates is two different answers/i),
    ).toBeInTheDocument();
  });

  it('names the first action instead of showing an empty workspace', async () => {
    renderView(null);
    const empty = await screen.findByTestId('company-no-selection');
    expect(empty).toHaveTextContent(/pick a company to begin/i);
    expect(empty).toHaveTextContent(/type a ticker or part of a company name/i);
  });

  it('does not ask the backend about a company nobody has named', async () => {
    renderView(null);
    await screen.findByTestId('company-no-selection');
    expect(apiClient.getCompanyOverview).not.toHaveBeenCalled();
    expect(apiClient.getPrices).not.toHaveBeenCalled();
  });

  it('hands the chosen symbol back to its caller rather than owning selection', async () => {
    const user = userEvent.setup();
    const { onSelectSymbol } = renderView(null);

    await waitFor(() => expect(screen.getByRole('combobox')).toBeEnabled());
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: /Deere/ }));

    expect(onSelectSymbol).toHaveBeenCalledWith('DE');
  });
});

describe('CompanyView, with a name', () => {
  it('shows who this is, and formats the close rather than dumping the float', async () => {
    renderView('CAT');

    const identity = await screen.findByTestId('company-identity');
    expect(identity).toHaveTextContent('CAT');
    expect(identity).toHaveTextContent('Caterpillar Inc.');
    expect(identity).toHaveTextContent('17.68 USD');
    expect(identity).not.toHaveTextContent('17.68000030517578');
  });

  it('never prints an empty sector, which 607 of 644 names carry', async () => {
    renderView('CAT');
    const identity = await screen.findByTestId('company-identity');
    // The badge grammar is a bordered mono pill; with a blank sector there is
    // no pill at all rather than an empty one.
    expect(within(identity).queryByText(/synthetic|macro|tech/i)).not.toBeInTheDocument();
  });

  it('renders all four panels, each carrying its own purpose', async () => {
    renderView('CAT');

    await screen.findByTestId('company-identity');
    for (const testId of [
      'company-price',
      'company-as-filed',
      'company-signals',
      'company-coverage',
    ]) {
      expect(screen.getByTestId(testId)).toBeInTheDocument();
    }
    expect(screen.getByText(/daily bars up to the as-of date and no further/i)).toBeInTheDocument();
  });

  it('cuts the price series at the as-of date, so the chart obeys the accounts', async () => {
    renderView('CAT');
    await waitFor(() =>
      expect(apiClient.getPrices).toHaveBeenCalledWith('CAT', undefined, expect.any(String)),
    );
    const [, , end] = vi.mocked(apiClient.getPrices).mock.calls[0];
    expect(end).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('re-reads both the accounts and the price when the as-of date moves', async () => {
    const user = userEvent.setup();
    renderView('CAT');
    await screen.findByTestId('company-identity');
    expect(apiClient.getCompanyOverview).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: '5Y ago' }));

    await waitFor(() => expect(apiClient.getCompanyOverview).toHaveBeenCalledTimes(2));
    const [, secondAsOf] = vi.mocked(apiClient.getCompanyOverview).mock.calls[1];
    const [, firstAsOf] = vi.mocked(apiClient.getCompanyOverview).mock.calls[0];
    expect(secondAsOf).not.toBe(firstAsOf);
    expect(apiClient.getPrices).toHaveBeenCalledTimes(2);
  });

  it('shows the accounts the overview already resolved, with filing dates', async () => {
    renderView('CAT');
    const table = await screen.findByTestId('company-as-filed-rows');
    expect(within(table).getByText('Revenue')).toBeInTheDocument();
    expect(within(table).getByText('67.1bn USD')).toBeInTheDocument();
    expect(within(table).getByText('2024-02-14')).toBeInTheDocument();
  });

  it('states coverage in both directions', async () => {
    renderView('CAT');
    await screen.findByTestId('company-coverage-body');
    expect(screen.getByTestId('company-coverage-filed')).toHaveTextContent(/filed — 2/i);
    expect(screen.getByTestId('company-coverage-missing')).toHaveTextContent(/never filed — 1/i);
  });

  it('scopes the signal firehose to this one name', async () => {
    renderView('CAT');
    const rows = await screen.findByTestId('company-signals-rows');
    expect(within(rows).getByText('breakout-20d')).toBeInTheDocument();
    expect(screen.getByText(/510 signals/)).toBeInTheDocument();
  });
});

describe('CompanyView, while the backend is still being written', () => {
  it('falls back to the thin fundamentals route when the overview 404s', async () => {
    // The composed route and the thin one ship separately. A 404 on the first
    // is not a reason to stop showing the accounts the second can still serve.
    vi.mocked(apiClient.getCompanyOverview).mockRejectedValue(
      new apiClient.ApiError(404, 'Not Found'),
    );
    vi.mocked(apiClient.getFundamentals).mockResolvedValue([
      makeFact({ concept: 'net_income', value: 10_300_000_000, filed_at: '2024-02-14' }),
    ]);

    renderView('CAT');

    const table = await screen.findByTestId('company-as-filed-rows');
    expect(within(table).getByText('Net income')).toBeInTheDocument();
    expect(within(table).getByText('10.3bn USD')).toBeInTheDocument();
  });

  it('still names the company from the catalogue when the overview is unserved', async () => {
    vi.mocked(apiClient.getCompanyOverview).mockRejectedValue(
      new apiClient.ApiError(404, 'Not Found'),
    );
    renderView('CAT');

    const identity = await screen.findByTestId('company-identity');
    expect(identity).toHaveTextContent('Caterpillar Inc.');
    expect(identity).toHaveTextContent(/overview not served/i);
  });

  it('reports a 404 as "not served", which is not "nothing is covered"', async () => {
    vi.mocked(apiClient.getCompanyOverview).mockRejectedValue(
      new apiClient.ApiError(404, 'Not Found'),
    );
    renderView('CAT');

    const state = await screen.findByTestId('company-coverage-state');
    expect(state).toHaveTextContent(/not served by this backend/i);
    expect(state).toHaveTextContent(/nothing here means “there is none”/i);
    expect(screen.queryByTestId('company-coverage-none')).not.toBeInTheDocument();
  });

  it('reports a 500 as a failed request, distinctly from a missing route', async () => {
    vi.mocked(apiClient.getCompanyOverview).mockRejectedValue(new apiClient.ApiError(500, 'boom'));
    renderView('CAT');

    const state = await screen.findByTestId('company-signals-state');
    expect(state).toHaveTextContent(/could not read it/i);
    expect(state).toHaveTextContent(/boom/);
    expect(state).not.toHaveTextContent(/not served by this backend/i);
  });

  it('retries the panel that failed', async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.getCompanyOverview).mockRejectedValueOnce(
      new apiClient.ApiError(500, 'boom'),
    );
    renderView('CAT');

    const state = await screen.findByTestId('company-signals-state');
    await user.click(within(state).getByRole('button', { name: /try again/i }));

    await waitFor(() => expect(screen.getByTestId('company-signals-rows')).toBeInTheDocument());
  });

  it('says what it is doing while it loads, in words', async () => {
    let release: () => void = () => undefined;
    vi.mocked(apiClient.getPrices).mockReturnValue(
      new Promise<apiClient.PriceBarList>((resolve) => {
        release = () => resolve({ total: 0, items: [] });
      }),
    );

    renderView('CAT');

    const state = await screen.findByTestId('company-price-state');
    expect(state).toHaveTextContent(/reading the price history/i);
    expect(state).toHaveTextContent(/resolved as of the date above/i);
    release();
  });

  it('says a name has no bars before this date rather than drawing an empty chart', async () => {
    vi.mocked(apiClient.getPrices).mockResolvedValue({ total: 0, items: [] });
    renderView('CAT');

    expect(await screen.findByTestId('company-price-empty')).toHaveTextContent(
      /no bars on or before this date/i,
    );
  });

  it('distinguishes a name that has never filed from one that filed later', async () => {
    vi.mocked(apiClient.getCompanyOverview).mockResolvedValue(
      makeOverview({ facts: [], concepts_available: [], concepts_missing: ['revenue'] }),
    );
    renderView('CAT');

    expect(await screen.findByTestId('company-as-filed-empty')).toHaveTextContent(
      /never filed any of the concepts/i,
    );
    expect(screen.getByTestId('company-coverage-none')).toHaveTextContent(
      /no fundamentals at all/i,
    );
  });
});
