import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { CompanyFundamentals } from '../../../src/api/types';
import { TiingoFundamentalsPanel } from '../../../src/research/company/TiingoFundamentalsPanel';

/** AAPL as production holds it, trimmed to two releases and three days. */
function aapl(overrides: Partial<CompanyFundamentals> = {}): CompanyFundamentals {
  return {
    symbol: 'AAPL.US',
    as_of: '2026-10-05',
    source: 'tiingo',
    profile: {
      name: 'Apple Inc',
      sector: 'Technology',
      industry: 'Consumer Electronics',
      sic_code: 3571,
      sic_sector: 'Manufacturing',
      sic_industry: 'Electronic Computers',
      location: 'California, USA',
      reporting_currency: 'usd',
      is_adr: false,
      is_active: true,
      perma_ticker: 'US000000000038',
      company_website: 'http://www.apple.com',
      sec_filing_website: 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193',
      statement_last_updated: '2026-08-21T01:01:17.444Z',
      daily_last_updated: '2026-10-03T02:16:32.911Z',
      fetched_at: '2026-10-05',
    },
    daily: [
      { date: '2026-09-30', market_cap: 4.891e12, pe_ratio: 37.9367, pb_ratio: 45.49 },
      { date: '2026-10-01', market_cap: 4.852e12, pe_ratio: 37.6292, pb_ratio: 45.12 },
      { date: '2026-10-02', market_cap: 4.901e12, pe_ratio: 38.0131, pb_ratio: 45.58 },
    ],
    releases: [
      { filed_at: '2026-07-31', fiscal_year: 2026, fiscal_quarter: 3, label: 'FY2026 Q3' },
      { filed_at: '2026-05-01', fiscal_year: 2026, fiscal_quarter: 2, label: 'FY2026 Q2' },
    ],
    lines: [
      {
        statement: 'incomeStatement',
        code: 'revenue',
        label: 'Revenue',
        description: 'Revenue',
        units: '$',
        values: [94.04e9, 95.36e9],
      },
      {
        statement: 'incomeStatement',
        code: 'netinc',
        label: 'Net Income',
        description: 'Net income',
        units: '$',
        values: [23.43e9, 24.78e9],
      },
      {
        statement: 'incomeStatement',
        code: 'epsDil',
        label: 'Earnings Per Share Diluted',
        units: '$',
        values: [1.57, null],
      },
      {
        statement: 'cashFlow',
        code: 'capex',
        label: 'Capital Expenditure',
        description: 'Money uses to upgrade or acquire property',
        units: '$',
        values: [-2.455e9, -1.971e9],
      },
      {
        statement: 'overview',
        code: 'roe',
        label: 'Return on Equity ROE',
        description: "Return on Shareholder's equity; ROE=Net Income/Shareholder's Equity",
        units: '%',
        values: [1.3718, 1.4669],
      },
    ],
    ...overrides,
  };
}

function renderPanel(data: CompanyFundamentals | null, extra: Partial<Parameters<typeof TiingoFundamentalsPanel>[0]> = {}) {
  const onReleases = vi.fn();
  render(
    <TiingoFundamentalsPanel
      symbol="AAPL.US"
      data={data}
      status="ready"
      message={null}
      releases={12}
      onReleases={onReleases}
      onRetry={vi.fn()}
      {...extra}
    />,
  );
  return { onReleases };
}

describe('Tiingo fundamentals — profile', () => {
  it('shows who Tiingo says this is, with links out', () => {
    renderPanel(aapl());

    const profile = screen.getByTestId('tiingo-profile');
    expect(profile).toHaveTextContent('Technology');
    expect(profile).toHaveTextContent('3571 · Electronic Computers');
    expect(profile).toHaveTextContent('US000000000038');
    expect(profile).toHaveTextContent('USD');
    expect(within(profile).getByRole('link', { name: /sec filings/i })).toHaveAttribute(
      'href',
      expect.stringContaining('CIK=0000320193'),
    );
    // Reports in dollars: nothing went through an FX rate.
    expect(profile).not.toHaveTextContent(/converted from/i);
  });

  it('says when the figures were converted from another currency', () => {
    const data = aapl();
    data.profile = { ...data.profile, reporting_currency: 'twd', is_adr: true };
    renderPanel(data);

    const profile = screen.getByTestId('tiingo-profile');
    expect(profile).toHaveTextContent('Converted from TWD');
    expect(profile).toHaveTextContent('ADR');
  });
});

describe('Tiingo fundamentals — daily valuation', () => {
  it('opens on P/E, latest first, with a chart to scale', () => {
    renderPanel(aapl());

    expect(screen.getByTestId('tiingo-valuation-latest')).toHaveTextContent('P/E (Tiingo) 38.0×');
    expect(screen.getByTestId('tiingo-valuation-latest')).toHaveTextContent('on 2026-10-02');
    expect(screen.getByTestId('tiingo-valuation-chart')).toHaveAccessibleName(
      'P/E (Tiingo) from 2026-09-30 to 2026-10-02, between 37.6× and 38.0×',
    );
  });

  it('switches metric', async () => {
    const user = userEvent.setup();
    renderPanel(aapl());

    await user.click(screen.getByRole('button', { name: 'Market cap' }));

    expect(screen.getByRole('button', { name: 'Market cap' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('tiingo-valuation-latest')).toHaveTextContent('Market cap $4.90T');
  });

  it('says so when a metric was never published, rather than drawing nothing', async () => {
    const user = userEvent.setup();
    renderPanel(aapl());

    await user.click(screen.getByRole('button', { name: 'PEG 1y' }));

    expect(screen.getByTestId('tiingo-valuation-latest')).toHaveTextContent('PEG 1y —');
    expect(screen.queryByTestId('tiingo-valuation-chart')).not.toBeInTheDocument();
  });
});

describe('Tiingo fundamentals — statements', () => {
  it('lays releases out as columns, newest first, each with its filing date', () => {
    renderPanel(aapl());

    const table = screen.getByTestId('tiingo-statement-table');
    const head = within(table).getAllByRole('columnheader').map((cell) => cell.textContent);
    expect(head).toEqual(['Field', 'FY2026 Q32026-07-31', 'FY2026 Q22026-05-01']);
  });

  it('shows a statement at a time, each figure in its own unit, blanks as dashes', () => {
    renderPanel(aapl());

    const table = screen.getByTestId('tiingo-statement-table');
    const revenue = within(table).getByRole('row', { name: /revenue/i });
    expect(revenue).toHaveTextContent('$94.0bn');
    const eps = within(table).getByRole('row', { name: /diluted/i });
    expect(eps).toHaveTextContent('$1.57');
    expect(eps).toHaveTextContent('—');
    // Cash flow is another tab.
    expect(within(table).queryByRole('row', { name: /capital expenditure/i })).toBeNull();
  });

  it('switches statement, and Tiingo’s percentages read as percentages', async () => {
    const user = userEvent.setup();
    renderPanel(aapl());

    await user.click(screen.getByRole('tab', { name: /ratios/i }));

    const row = within(screen.getByTestId('tiingo-statement-table')).getByRole('row', {
      name: /return on equity/i,
    });
    expect(row).toHaveTextContent('137.2%');
  });

  it('carries Tiingo’s definition on each field', () => {
    renderPanel(aapl());

    const field = within(screen.getByTestId('tiingo-statement-table')).getByRole('rowheader', {
      name: /net income/i,
    });
    expect(field).toHaveAttribute('title', 'Net income (netinc)');
  });

  it('filters fields by name or Tiingo code', async () => {
    const user = userEvent.setup();
    renderPanel(aapl());

    await user.type(screen.getByLabelText('Filter fields'), 'netinc');

    const rows = within(screen.getByTestId('tiingo-statement-table')).getAllByRole('rowheader');
    expect(rows.map((row) => row.textContent)).toEqual(['Net Incomenetinc']);
  });

  it('asks for more releases when the reader does', async () => {
    const user = userEvent.setup();
    const { onReleases } = renderPanel(aapl());

    await user.selectOptions(screen.getByLabelText('How many releases'), '20');

    expect(onReleases).toHaveBeenCalledWith(20);
  });
});

describe('Tiingo fundamentals — when there is nothing', () => {
  it('names an empty answer as a coverage gap, not a finding', () => {
    renderPanel(aapl({ profile: null, daily: [], releases: [], lines: [] }));

    expect(screen.getByTestId('tiingo-fundamentals-empty')).toHaveTextContent(
      /tiingo has published nothing for AAPL\.US/i,
    );
  });

  it('reads as loading while the request is out', () => {
    renderPanel(null, { status: 'loading' });

    expect(screen.getByTestId('tiingo-fundamentals-state')).toHaveTextContent(/reading tiingo/i);
  });
});
