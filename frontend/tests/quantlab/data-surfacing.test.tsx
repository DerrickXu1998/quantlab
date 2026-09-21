import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import { DatasetProvider } from '../../src/api/DatasetProvider';
import { SignalFilters } from '../../src/components/SignalFilters';
import * as fundamentals from '../../src/quantlab/data/fundamentals';
import { useWatchlist } from '../../src/quantlab/data/useWatchlist';
import { FeedProvider } from '../../src/quantlab/feed/FeedProvider';
import { FundamentalsPanel } from '../../src/quantlab/panels/FundamentalsPanel';
import { WatchlistRail } from '../../src/quantlab/panels/WatchlistRail';
import { IndicatorsView } from '../../src/quantlab/views/IndicatorsView';
import { ThemeProvider } from '../../src/theme/ThemeProvider';
import { WorkspaceProvider, useWorkspace } from '../../src/workspace/WorkspaceContext';
import { makeInstrument, makeMacroInstrument, makeSignal } from '../fixtures';
import { installCanvas2d } from '../mocks/canvas-2d';
import { installResizeObserver } from '../mocks/resize-observer';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    getHealth: vi.fn(),
    listInstruments: vi.fn(),
    getPrices: vi.fn(),
    listSignals: vi.fn(),
  };
});

vi.mock('../../src/quantlab/data/fundamentals', async (importOriginal) => {
  const actual = await importOriginal<typeof fundamentals>();
  return {
    ...actual,
    listFundamentalConcepts: vi.fn(),
    getFundamentalSeries: vi.fn(),
  };
});

installResizeObserver();
installCanvas2d();

const equity = makeInstrument();
const macro = makeMacroInstrument();

const revenueConcept = {
  concept: 'revenue',
  provider: 'sec_edgar',
  unit: 'USD',
  fact_count: 12,
  first_filed: '2023-02-10',
  last_filed: '2024-11-08',
  derived: false,
};

const derivedConcept = {
  concept: 'short_volume_ratio',
  provider: 'finra',
  unit: 'ratio',
  fact_count: 240,
  first_filed: '2024-01-02',
  last_filed: '2024-12-31',
  derived: true,
};

function seriesFor(transform: string): fundamentals.FundamentalSeries {
  if (transform === 'raw_facts') {
    return {
      symbol: 'ZZTRND',
      concept: 'revenue',
      transform: 'raw_facts',
      point_in_time: true,
      provenance: 'SEC EDGAR companyfacts, as filed.',
      total: 2,
      items: [
        {
          value: 1.1e9,
          period_start: '2023-01-01',
          period_end: '2023-12-31',
          filed_at: '2024-02-10',
          provider: 'sec_edgar',
          unit: 'USD',
          holder: null,
        },
        // A restatement: the same period filed again with a revised value.
        {
          value: 1.2e9,
          period_start: '2023-01-01',
          period_end: '2023-12-31',
          filed_at: '2024-04-15',
          provider: 'sec_edgar',
          unit: 'USD',
          holder: null,
        },
      ],
    };
  }
  return {
    symbol: 'ZZTRND',
    concept: 'revenue',
    transform: transform as 'raw' | 'yoy_growth',
    point_in_time: true,
    provenance:
      transform === 'yoy_growth'
        ? 'Year-over-year growth of sec_edgar revenue, aligned by period_end.'
        : 'As-of step series of sec_edgar revenue; a value is knowable from its filed_at.',
    total: 3,
    items: [
      { date: '2024-02-10', value: transform === 'yoy_growth' ? 0.11 : 1.1e9 },
      { date: '2024-04-15', value: transform === 'yoy_growth' ? 0.12 : 1.2e9 },
      { date: '2024-08-09', value: transform === 'yoy_growth' ? 0.09 : 1.15e9 },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = '';
  vi.mocked(apiClient.getHealth).mockResolvedValue({
    status: 'ok',
    dataset: 'warehouse',
    seeded: true,
    signal_count: 0,
  });
  vi.mocked(apiClient.listInstruments).mockResolvedValue({ total: 2, items: [equity, macro] });
  vi.mocked(apiClient.getPrices).mockResolvedValue({
    total: 2,
    items: [
      { symbol: 'ZZTRND', date: '2024-12-30', open: 10, high: 11, low: 9, close: 10.5, volume: 100 },
      { symbol: 'ZZTRND', date: '2024-12-31', open: 10.5, high: 11, low: 10, close: 10.8, volume: 120 },
    ],
  });
  vi.mocked(apiClient.listSignals).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(fundamentals.listFundamentalConcepts).mockResolvedValue({
    symbol: 'ZZTRND',
    total: 0,
    items: [],
  });
  vi.mocked(fundamentals.getFundamentalSeries).mockImplementation((_s, _c, transform) =>
    Promise.resolve(seriesFor(transform ?? 'raw')),
  );
});

describe('useWatchlist feed exclusion', () => {
  function Probe() {
    const { instruments, seeds, loading } = useWatchlist();
    if (loading) return null;
    return (
      <output
        data-testid="probe"
        data-seeds={JSON.stringify(Object.keys(seeds).sort())}
        data-instruments={JSON.stringify(instruments.map((item) => item.symbol).sort())}
      />
    );
  }

  it('lists macro instruments but never seeds a simulated tick for one', async () => {
    render(<Probe />);

    const probe = await screen.findByTestId('probe');
    // Both kinds are on the rail…
    expect(JSON.parse(probe.dataset.instruments ?? '[]')).toEqual(['UST10Y.FRED', 'ZZTRND']);
    // …but only the equity enters the random walk. A per-second "tick" on a
    // Treasury yield would be invention dressed as data.
    expect(JSON.parse(probe.dataset.seeds ?? '[]')).toEqual(['ZZTRND']);
  });
});

describe('WatchlistRail grouping', () => {
  function renderRail() {
    return render(
      <FeedProvider seeds={{ ZZTRND: 100 }} rng={() => 0.5}>
        <WatchlistRail
          instruments={[macro, equity]}
          selected={null}
          onSelect={() => {}}
          error={null}
        />
      </FeedProvider>,
    );
  }

  it('groups the rail into equities and macro series', async () => {
    renderRail();

    const equities = await screen.findByTestId('watchlist-group-equity');
    const macroGroup = screen.getByTestId('watchlist-group-macro');
    expect(within(equities).getByText('ZZTRND')).toBeInTheDocument();
    expect(within(macroGroup).getByText('UST10Y.FRED')).toBeInTheDocument();
    // Equities first, macro second.
    const groups = screen.getAllByTestId(/^watchlist-group-/);
    expect(groups[0]).toHaveTextContent('Equities');
    expect(groups[1]).toHaveTextContent('Macro series');
  });

  it('shows a macro row’s full series name and no simulated quote', async () => {
    renderRail();

    const macroGroup = await screen.findByTestId('watchlist-group-macro');
    expect(macroGroup).toHaveTextContent('10-Year Treasury constant maturity yield');
    const badge = within(macroGroup).getByText('Macro');
    expect(badge).toHaveAttribute('title', expect.stringMatching(/excluded from the simulated tick feed/i));
  });

  it('omits the macro group entirely when the dataset has none', async () => {
    render(
      <FeedProvider seeds={{ ZZTRND: 100 }} rng={() => 0.5}>
        <WatchlistRail instruments={[equity]} selected={null} onSelect={() => {}} error={null} />
      </FeedProvider>,
    );

    expect(await screen.findByTestId('watchlist-group-equity')).toBeInTheDocument();
    expect(screen.queryByTestId('watchlist-group-macro')).not.toBeInTheDocument();
  });
});

describe('IndicatorsView macro mode', () => {
  function renderMarket() {
    return render(
      <ThemeProvider>
        <FeedProvider seeds={{ ZZTRND: 100 }} rng={() => 0.5}>
          <IndicatorsView instruments={[equity, macro]} feedError={null} />
        </FeedProvider>
      </ThemeProvider>,
    );
  }

  it('renders macro history as a line, badges it, and offers no live ticks', async () => {
    vi.mocked(apiClient.getPrices).mockResolvedValue({
      total: 2,
      items: [
        { symbol: 'UST10Y.FRED', date: '2024-12-30', open: 4.2, high: 4.2, low: 4.2, close: 4.2, volume: 0 },
        { symbol: 'UST10Y.FRED', date: '2024-12-31', open: 4.25, high: 4.25, low: 4.25, close: 4.25, volume: 0 },
      ],
    });
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole('region', { name: /ZZTRND — intraday/i });

    await user.click(screen.getByText('UST10Y.FRED'));

    const panel = await screen.findByRole('region', { name: /UST10Y\.FRED — daily history/i });
    // The badge says what the number is: a value, not a price.
    expect(within(panel).getByTestId('macro-badge')).toHaveTextContent(/value, not price/i);
    // A line chart from stored bars — never candlesticks, never a volume pane.
    expect(await within(panel).findByTestId('macro-history-chart-summary')).toBeInTheDocument();
    expect(within(panel).queryByTestId('price-chart')).not.toBeInTheDocument();
    // No simulated feed for a yield: the toggle is visibly disabled, with the reason.
    expect(within(panel).getByRole('button', { name: /live ticks/i })).toBeDisabled();
    expect(within(panel).queryByTestId('simulated-tag')).toBeNull();
  });

  it('keeps equities on the candlestick path in daily mode', async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole('region', { name: /ZZTRND — intraday/i });

    await user.click(screen.getByRole('button', { name: /daily history/i }));

    const panel = await screen.findByRole('region', { name: /ZZTRND — daily history/i });
    expect(await within(panel).findByTestId('price-chart')).toBeInTheDocument();
    expect(within(panel).queryByTestId('macro-badge')).not.toBeInTheDocument();
  });
});

describe('FundamentalsPanel', () => {
  function renderPanel(symbol = 'ZZTRND') {
    return render(
      <DatasetProvider>
        <FundamentalsPanel symbol={symbol} />
      </DatasetProvider>,
    );
  }

  it('renders a loading state while the concepts catalog is fetched', () => {
    vi.mocked(fundamentals.listFundamentalConcepts).mockReturnValue(new Promise(() => {}));
    renderPanel();

    expect(screen.getByText(/loading fundamentals/i)).toBeInTheDocument();
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('names the demo dataset as the reason there are no fundamentals', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue({
      status: 'ok',
      dataset: 'sqlite',
      seeded: true,
      signal_count: 0,
    });
    renderPanel();

    const empty = await screen.findByTestId('fundamentals-demo-empty');
    expect(empty).toHaveTextContent(/synthetic demo dataset carries no fundamentals/i);
    expect(empty).toHaveTextContent(/warehouse/i);
  });

  it('has a plainer empty state when the warehouse simply has none filed', async () => {
    renderPanel();

    const empty = await screen.findByTestId('fundamentals-empty');
    expect(empty).toHaveTextContent(/no fundamentals filed/i);
    expect(empty).toHaveTextContent('ZZTRND');
  });

  it('turns a failed catalog read into an error with a retry that recovers', async () => {
    vi.mocked(fundamentals.listFundamentalConcepts)
      .mockRejectedValueOnce(new apiClient.ApiError(500, 'boom'))
      .mockResolvedValue({ symbol: 'ZZTRND', total: 1, items: [revenueConcept] });
    const user = userEvent.setup();
    renderPanel();

    const error = await screen.findByTestId('fundamentals-error');
    expect(error).toHaveAttribute('role', 'alert');

    await user.click(within(error).getByRole('button', { name: /retry/i }));

    expect(await screen.findByTestId('fundamental-concepts')).toBeInTheDocument();
    expect(fundamentals.listFundamentalConcepts).toHaveBeenCalledTimes(2);
  });

  it('lists concepts as chips, marking the derived ones', async () => {
    vi.mocked(fundamentals.listFundamentalConcepts).mockResolvedValue({
      symbol: 'ZZTRND',
      total: 2,
      items: [revenueConcept, derivedConcept],
    });
    renderPanel();

    const chips = await screen.findByTestId('fundamental-concepts');
    expect(within(chips).getByText('revenue')).toBeInTheDocument();
    expect(within(chips).getByText('12')).toBeInTheDocument();
    const derived = within(chips).getByText('short_volume_ratio').closest('button');
    expect(within(derived as HTMLElement).getByText(/derived/i)).toBeInTheDocument();
  });

  it('renders the PIT series as a step line with provenance and the filings table', async () => {
    vi.mocked(fundamentals.listFundamentalConcepts).mockResolvedValue({
      symbol: 'ZZTRND',
      total: 1,
      items: [revenueConcept],
    });
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByText('revenue'));

    // The chart series is the as-of step series; the table is filing-level.
    expect(await screen.findByTestId('fundamentals-chart-summary')).toHaveTextContent(
      /3 points from 2024-02-10 to 2024-08-09/,
    );
    expect(screen.getByTestId('fundamentals-provenance')).toHaveTextContent(/as-of step series/i);
    expect(screen.getByTestId('pit-badge')).toHaveTextContent(/point-in-time/i);

    const filings = screen.getByTestId('fundamentals-filings');
    // The restatement is visible: one period, two filings.
    expect(within(filings).getAllByText('2023-12-31')).toHaveLength(2);
    expect(within(filings).getByText('2024-02-10')).toBeInTheDocument();
    expect(within(filings).getByText('2024-04-15')).toBeInTheDocument();

    expect(fundamentals.getFundamentalSeries).toHaveBeenCalledWith('ZZTRND', 'revenue', 'raw');
    expect(fundamentals.getFundamentalSeries).toHaveBeenCalledWith('ZZTRND', 'revenue', 'raw_facts');
  });

  it('switches the chart to year-over-year growth on the toggle', async () => {
    vi.mocked(fundamentals.listFundamentalConcepts).mockResolvedValue({
      symbol: 'ZZTRND',
      total: 1,
      items: [revenueConcept],
    });
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByText('revenue'));
    await screen.findByTestId('fundamentals-chart-summary');
    await user.click(screen.getByRole('button', { name: /yoy growth/i }));

    await waitFor(() =>
      expect(fundamentals.getFundamentalSeries).toHaveBeenCalledWith(
        'ZZTRND',
        'revenue',
        'yoy_growth',
      ),
    );
    expect(await screen.findByTestId('fundamentals-provenance')).toHaveTextContent(
      /year-over-year/i,
    );
  });
});

describe('Research kind filter', () => {
  function Harness() {
    const { instruments, filters, changeFilters, signals, status } = useWorkspace();
    return (
      <>
        <SignalFilters
          instruments={instruments}
          ruleNames={[]}
          value={filters}
          onChange={changeFilters}
        />
        <ul data-testid="kind-rows">
          {status === 'ready'
            ? signals.map((signal) => <li key={signal.id}>{signal.symbol}</li>)
            : null}
        </ul>
      </>
    );
  }

  it('separates equity signals from macro-series signals', async () => {
    vi.mocked(apiClient.listSignals).mockResolvedValue({
      total: 2,
      items: [
        makeSignal({ id: 1, symbol: 'ZZTRND' }),
        makeSignal({ id: 2, symbol: 'UST10Y.FRED' }),
      ],
    });
    const user = userEvent.setup();
    render(
      <WorkspaceProvider>
        <Harness />
      </WorkspaceProvider>,
    );

    const rows = await screen.findByTestId('kind-rows');
    await waitFor(() => expect(within(rows).getAllByRole('listitem')).toHaveLength(2));

    const group = screen.getByTestId('kind-filter');
    await user.click(within(group).getByRole('radio', { name: /macro/i }));

    await waitFor(() => {
      expect(within(rows).getAllByRole('listitem')).toHaveLength(1);
    });
    expect(within(rows).getByText('UST10Y.FRED')).toBeInTheDocument();

    await user.click(within(group).getByRole('radio', { name: /equities/i }));
    await waitFor(() => expect(within(rows).getAllByRole('listitem')).toHaveLength(1));
    expect(within(rows).getByText('ZZTRND')).toBeInTheDocument();
  });
});
