import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AsFiledPanel } from '../../../src/research/company/AsFiledPanel';
import { CoveragePanel } from '../../../src/research/company/CoveragePanel';
import { SignalHistoryPanel } from '../../../src/research/company/SignalHistoryPanel';
import { resolveInForce } from '../../../src/research/company/useCompany';
import { makeFact } from './fixtures';

const READY = { status: 'ready', message: null, onRetry: vi.fn() } as const;

describe('every panel says what it is', () => {
  it('AsFiled names the accounts and the filing date', () => {
    render(<AsFiledPanel symbol="CAT" asOf="2024-06-30" rows={[]} hasAnyFilings {...READY} />);
    expect(
      screen.getByText(/the accounts as they were public on the as-of date/i),
    ).toBeInTheDocument();
  });

  it('SignalHistory names the rules and when they fired', () => {
    render(<SignalHistoryPanel symbol="CAT" signals={[]} total={0} {...READY} />);
    expect(screen.getByText(/which rules have ever fired on this name/i)).toBeInTheDocument();
  });

  it('Coverage names the distinction it exists to draw', () => {
    render(<CoveragePanel symbol="CAT" available={[]} missing={[]} {...READY} />);
    expect(
      screen.getByText(/an absent concept was never filed — it is not a zero/i),
    ).toBeInTheDocument();
  });
});

describe('AsFiledPanel', () => {
  const rows = resolveInForce([
    makeFact({
      concept: 'revenue',
      value: 67_060_000_000,
      filed_at: '2024-02-14',
      period_end: '2023-12-31',
      days_stale: 137,
    }),
    makeFact({
      concept: 'revenue',
      value: 59_400_000_000,
      filed_at: '2023-02-14',
      period_end: '2022-12-31',
      days_stale: 502,
    }),
  ]);

  it('renders a filed magnitude at human scale, never a raw float', () => {
    render(<AsFiledPanel symbol="CAT" asOf="2024-06-30" rows={rows} hasAnyFilings {...READY} />);
    const table = screen.getByTestId('company-as-filed-rows');
    expect(within(table).getByText('67.1bn USD')).toBeInTheDocument();
    expect(within(table).queryByText(/67060000000/)).not.toBeInTheDocument();
  });

  it('puts the filing date beside the figure, which is the whole discipline', () => {
    render(<AsFiledPanel symbol="CAT" asOf="2024-06-30" rows={rows} hasAnyFilings {...READY} />);
    const table = screen.getByTestId('company-as-filed-rows');
    expect(within(table).getByText('2024-02-14')).toBeInTheDocument();
    expect(within(table).getAllByText(/months ago|days ago|years ago/)).toHaveLength(2);
  });

  it('marks a figure older than the rules will honour, without hiding it', () => {
    render(<AsFiledPanel symbol="CAT" asOf="2024-06-30" rows={rows} hasAnyFilings {...READY} />);
    const table = screen.getByTestId('company-as-filed-rows');
    // Shown, so the reader can see the accounts existed; marked, so they know
    // a fundamental rule would not have traded on them.
    expect(within(table).getByText('59.4bn USD')).toBeInTheDocument();
    expect(within(table).getByText(/^stale$/i)).toBeInTheDocument();
  });

  it('marks the superseded filing rather than silently dropping it', () => {
    render(<AsFiledPanel symbol="CAT" asOf="2024-06-30" rows={rows} hasAnyFilings {...READY} />);
    expect(screen.getByText(/^superseded$/i)).toBeInTheDocument();
    expect(screen.getByText(/1 in force · 1 superseded/i)).toBeInTheDocument();
  });

  it('separates "nothing yet on this date" from "nothing ever"', () => {
    const { unmount } = render(
      <AsFiledPanel symbol="CAT" asOf="2011-01-01" rows={[]} hasAnyFilings {...READY} />,
    );
    expect(screen.getByTestId('company-as-filed-empty')).toHaveTextContent(
      /has filings, but none had been published by 2011-01-01/i,
    );
    unmount();

    render(
      <AsFiledPanel symbol="CAT" asOf="2024-06-30" rows={[]} hasAnyFilings={false} {...READY} />,
    );
    expect(screen.getByTestId('company-as-filed-empty')).toHaveTextContent(
      /never filed any of the concepts.*not a set of zeroes/i,
    );
  });

  it('admits when coverage itself could not be read', () => {
    render(
      <AsFiledPanel symbol="CAT" asOf="2024-06-30" rows={[]} hasAnyFilings={null} {...READY} />,
    );
    expect(screen.getByTestId('company-as-filed-empty')).toHaveTextContent(
      /whether it has ever filed is unknown/i,
    );
  });

  it('calls an unserved route a gap in the API, not an absence of accounts', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <AsFiledPanel
        symbol="CAT"
        asOf="2024-06-30"
        rows={[]}
        hasAnyFilings={null}
        status="unsupported"
        message={null}
        onRetry={onRetry}
      />,
    );

    const state = screen.getByTestId('company-as-filed-state');
    expect(state).toHaveTextContent(/not served by this backend/i);
    expect(state).toHaveTextContent(/gap in the API, not a fact about the company/i);
    expect(state).toHaveTextContent(/instruments\/\{symbol\}\/fundamentals/);

    await user.click(within(state).getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('gives loading and error their own words', () => {
    const { unmount } = render(
      <AsFiledPanel
        symbol="CAT"
        asOf="2024-06-30"
        rows={[]}
        hasAnyFilings={null}
        status="loading"
        message={null}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByTestId('company-as-filed-state')).toHaveTextContent(
      /reading the accounts as filed/i,
    );
    unmount();

    render(
      <AsFiledPanel
        symbol="CAT"
        asOf="2024-06-30"
        rows={[]}
        hasAnyFilings={null}
        status="error"
        message="Backend unreachable at /api/v1"
        onRetry={vi.fn()}
      />,
    );
    const state = screen.getByTestId('company-as-filed-state');
    expect(state).toHaveTextContent(/could not read it/i);
    expect(state).toHaveTextContent(/backend unreachable/i);
    expect(state).toHaveTextContent(/the company may be fine; the request was not/i);
  });
});

describe('SignalHistoryPanel', () => {
  const signals = [
    { rule_name: 'rsi-threshold', count: 98, last_date: '2024-05-02', last_direction: 'bearish' },
    { rule_name: 'breakout-20d', count: 412, last_date: '2024-06-21', last_direction: 'bullish' },
  ] as const;

  it('orders by how often each rule fired, and groups counts for reading', () => {
    render(<SignalHistoryPanel symbol="CAT" signals={[...signals]} total={510} {...READY} />);
    const rows = within(screen.getByTestId('company-signals-rows')).getAllByRole('row');
    // Row 0 is the header.
    expect(rows[1]).toHaveTextContent('breakout-20d');
    expect(rows[1]).toHaveTextContent('412');
    expect(rows[2]).toHaveTextContent('rsi-threshold');
  });

  it('renders a missing last direction as a dash, never as a default', () => {
    render(
      <SignalHistoryPanel
        symbol="CAT"
        signals={[{ rule_name: 'sma-crossover', count: 3, last_date: null, last_direction: null }]}
        total={3}
        {...READY}
      />,
    );
    const row = within(screen.getByTestId('company-signals-rows')).getAllByRole('row')[1];
    expect(within(row).getAllByText('—')).toHaveLength(2);
  });

  it('does not let silence read as "this rule never triggered"', () => {
    render(<SignalHistoryPanel symbol="CAT" signals={[]} total={0} {...READY} />);
    expect(screen.getByTestId('company-signals-empty')).toHaveTextContent(
      /"not yet run" as easily as "never triggered"/i,
    );
  });
});

describe('CoveragePanel', () => {
  it('lists what was never filed by name, rather than leaving a gap', () => {
    render(
      <CoveragePanel
        symbol="CAT"
        available={['revenue', 'net_income']}
        missing={['gross_profit', 'net_short_position']}
        {...READY}
      />,
    );

    const missing = screen.getByTestId('company-coverage-missing');
    expect(missing).toHaveTextContent(/never filed — 2/i);
    expect(within(missing).getByText('Gross profit')).toBeInTheDocument();
    expect(missing).toHaveTextContent(/unmeasurable for this name, not zero/i);
  });

  it('writes concepts the way an analyst says them, not as column names', () => {
    render(
      <CoveragePanel symbol="CAT" available={['operating_cash_flow']} missing={[]} {...READY} />,
    );
    const filed = screen.getByTestId('company-coverage-filed');
    expect(within(filed).getByText('Operating cash flow')).toBeInTheDocument();
    expect(within(filed).queryByText('operating_cash_flow')).not.toBeInTheDocument();
  });

  it('says a name with no filings cannot be traded by a fundamental rule', () => {
    render(<CoveragePanel symbol="ZZTRND" available={[]} missing={['revenue']} {...READY} />);
    const none = screen.getByTestId('company-coverage-none');
    expect(none).toHaveTextContent(/no fundamentals at all/i);
    expect(none).toHaveTextContent(/cannot trade/i);
    expect(none).toHaveTextContent(/different outcome from finding no trades/i);
  });

  it('is explicit when a name has filed everything the warehouse maps', () => {
    render(<CoveragePanel symbol="CAT" available={['revenue']} missing={[]} {...READY} />);
    expect(screen.getByTestId('company-coverage-missing')).toHaveTextContent(
      /has filed every concept this warehouse maps/i,
    );
  });

  it('does not report zero coverage when the route was not served', () => {
    render(
      <CoveragePanel
        symbol="CAT"
        available={[]}
        missing={[]}
        status="unsupported"
        message={null}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('company-coverage-none')).not.toBeInTheDocument();
    expect(screen.getByTestId('company-coverage-state')).toHaveTextContent(
      /not served by this backend/i,
    );
  });
});
