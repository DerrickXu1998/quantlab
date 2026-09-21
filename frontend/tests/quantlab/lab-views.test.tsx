import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import type { Instrument } from '../../src/api/client';
import { bollinger, lastValue, macd, rsi, vwap } from '../../src/quantlab/data/indicators';
import { derivePositions, type Fill } from '../../src/quantlab/data/execution';
import { buildOrderBook } from '../../src/quantlab/data/orderBook';
import { FeedProvider } from '../../src/quantlab/feed/FeedProvider';
import { ExecutionView } from '../../src/quantlab/views/ExecutionView';
import { IndicatorsView } from '../../src/quantlab/views/IndicatorsView';
import { ThemeProvider } from '../../src/theme/ThemeProvider';
import { installCanvas2d } from '../mocks/canvas-2d';
import { installResizeObserver } from '../mocks/resize-observer';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return { ...actual, getPrices: vi.fn() };
});

// The fundamentals panel's fetches stay out of these tests; the states they
// produce are covered in data-surfacing.test.tsx.
vi.mock('../../src/quantlab/data/fundamentals', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/quantlab/data/fundamentals')>();
  return {
    ...actual,
    listFundamentalConcepts: vi.fn().mockResolvedValue({ symbol: 'ZZTRND', total: 0, items: [] }),
    getFundamentalSeries: vi.fn(),
  };
});

installResizeObserver();
installCanvas2d();

const instruments = [
  { symbol: 'ZZTRND', name: 'Trend Co', currency: 'USD', regime: null },
  { symbol: 'ZZMEAN', name: 'Mean Co', currency: 'USD', regime: null },
] as unknown as Instrument[];

beforeEach(() => {
  window.location.hash = '';
});

function renderWithFeed(ui: React.ReactElement) {
  // A fixed rng makes the walk deterministic; the seed is the last close.
  return render(
    <ThemeProvider>
      <FeedProvider seeds={{ ZZTRND: 100, ZZMEAN: 50 }} rng={() => 0.5}>
        {ui}
      </FeedProvider>
    </ThemeProvider>,
  );
}

describe('indicator math', () => {
  it('pads with null until the warmup is done, never a zero', () => {
    const values = Array.from({ length: 20 }, (_, i) => 100 + i);

    const result = rsi(values, 14);

    expect(result).toHaveLength(20);
    expect(result.slice(0, 14).every((value) => value === null)).toBe(true);
    expect(lastValue(result)).not.toBeNull();
  });

  it('reads 100 on a series that only rises', () => {
    const values = Array.from({ length: 30 }, (_, i) => 100 + i);

    expect(lastValue(rsi(values))).toBeCloseTo(100, 6);
  });

  it('puts the Bollinger mid on the SMA and the bands symmetric around it', () => {
    const values = Array.from({ length: 25 }, (_, i) => 100 + Math.sin(i) * 5);

    const bands = bollinger(values, 20, 2);
    const last = bands[bands.length - 1];

    const sma = values.slice(-20).reduce((a, b) => a + b, 0) / 20;
    expect(last.mid).toBeCloseTo(sma, 10);
    expect(last.upper! - last.mid!).toBeCloseTo(last.mid! - last.lower!, 10);
    expect(bands[0].mid).toBeNull();
  });

  it('keeps the MACD histogram as line minus signal', () => {
    const values = Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 3) * 10);

    const result = macd(values);
    const index = values.length - 1;

    expect(result.histogram[index]).toBeCloseTo(
      (result.line[index] as number) - (result.signal[index] as number),
      10,
    );
  });

  it('computes VWAP as the cumulative mean of the series', () => {
    const result = vwap([10, 20, 30]);

    expect(result).toEqual([10, 15, 20]);
  });
});

describe('Indicators view', () => {
  it('explains an empty watchlist instead of charting nothing', () => {
    renderWithFeed(<IndicatorsView instruments={[]} feedError={null} />);

    expect(screen.getByTestId('indicators-empty')).toHaveTextContent(/no instruments/i);
  });

  it('distinguishes a dead feed from an empty one', () => {
    renderWithFeed(<IndicatorsView instruments={instruments} feedError="backend down" />);

    const error = screen.getByTestId('indicators-feed-error');
    expect(error).toHaveAttribute('role', 'alert');
  });

  it('selects the first instrument and charts it without being asked', async () => {
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);

    const panel = await screen.findByRole('region', { name: /ZZTRND — intraday/i });
    expect(within(panel).getByTestId('price-chart-summary')).toBeInTheDocument();
    // Anything showing a tick walks away from the real close and says so.
    expect(within(panel).getAllByTestId('simulated-tag').length).toBeGreaterThan(0);
  });

  it('shows RSI and MACD as sub-panels only while toggled on', async () => {
    const user = userEvent.setup();
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);
    await screen.findByRole('region', { name: /intraday/i });

    expect(screen.queryByRole('region', { name: /^RSI/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /^MACD/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^RSI 14/ }));
    await user.click(screen.getByRole('button', { name: /^MACD 12/ }));

    expect(screen.getByRole('region', { name: /^RSI \(14\)/ })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /^MACD \(12, 26, 9\)/ })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^RSI 14/ }));
    expect(screen.queryByRole('region', { name: /^RSI/ })).not.toBeInTheDocument();
  });

  it('keeps Bollinger and VWAP as overlays — toggling them adds no sub-panel', async () => {
    const user = userEvent.setup();
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);
    await screen.findByRole('region', { name: /intraday/i });

    await user.click(screen.getByRole('button', { name: /^BB 20/ }));
    await user.click(screen.getByRole('button', { name: /^VWAP/ }));

    expect(screen.queryByRole('region', { name: /bollinger|vwap/i })).not.toBeInTheDocument();
    // Three regions only: the instruments rail, the price chart, and the
    // fundamentals panel (empty here — the concepts fetch is mocked to none).
    expect(screen.getAllByRole('region').map((region) => region.getAttribute('aria-label')))
      .toEqual(['Instruments', expect.stringMatching(/intraday/i), expect.stringMatching(/fundamentals/i)]);
  });
});

describe('order book generation', () => {
  it('is a pure function of the mid — the same price draws the same book', () => {
    expect(buildOrderBook(100.25)).toEqual(buildOrderBook(100.25));
  });

  it('keeps bids below and asks above the mid, with a positive spread', () => {
    const book = buildOrderBook(100);

    expect(book.bids).toHaveLength(10);
    expect(book.asks).toHaveLength(10);
    expect(book.spread).toBeGreaterThan(0);
    for (const level of book.bids) expect(level.price).toBeLessThan(100);
    for (const level of book.asks) expect(level.price).toBeGreaterThan(100);
  });
});

describe('position netting', () => {
  const fill = (overrides: Partial<Fill>): Fill => ({
    id: 0,
    symbol: 'ZZTRND',
    side: 'BUY',
    qty: 10,
    price: 100,
    time: '12:00:00',
    ...overrides,
  });

  it('averages into a growing position', () => {
    const [position] = derivePositions([fill({}), fill({ price: 120 })]);

    expect(position.qty).toBe(20);
    expect(position.avgCost).toBeCloseTo(110, 10);
  });

  it('reduces without moving the average cost', () => {
    const [position] = derivePositions([fill({}), fill({ price: 120 }), fill({ side: 'SELL', qty: 5 })]);

    expect(position.qty).toBe(15);
    expect(position.avgCost).toBeCloseTo(110, 10);
  });

  it('drops a flat position entirely', () => {
    expect(derivePositions([fill({}), fill({ side: 'SELL', qty: 10 })])).toHaveLength(0);
  });
});

describe('Execution view', () => {
  it('renders the book around the feed price, with the spread in the middle', async () => {
    renderWithFeed(<ExecutionView instruments={instruments} feedError={null} />);

    expect(await screen.findByTestId('order-book')).toBeInTheDocument();
    expect(screen.getByTestId('order-book-spread')).toHaveTextContent(/spread/i);
    // Nothing traded yet: an explained absence, not a blank table.
    expect(screen.getByTestId('fills-empty')).toHaveTextContent(/no fills yet/i);
    expect(screen.getByTestId('execution-positions-empty')).toHaveTextContent(/no positions/i);
  });

  it('explains an empty watchlist', () => {
    renderWithFeed(<ExecutionView instruments={[]} feedError={null} />);

    expect(screen.getByTestId('execution-empty')).toHaveTextContent(/no instruments/i);
  });

  it('shows the limit price field only for a limit order', async () => {
    const user = userEvent.setup();
    renderWithFeed(<ExecutionView instruments={instruments} feedError={null} />);
    await screen.findByTestId('order-ticket');

    expect(screen.queryByLabelText(/limit price/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'limit' }));
    expect(screen.getByLabelText(/limit price/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'market' }));
    expect(screen.queryByLabelText(/limit price/i)).not.toBeInTheDocument();
  });

  it('appends a fill and opens a position when the ticket is submitted', async () => {
    const user = userEvent.setup();
    renderWithFeed(<ExecutionView instruments={instruments} feedError={null} />);
    await screen.findByTestId('order-book');

    await user.click(screen.getByRole('button', { name: /submit order/i }));

    const fills = await screen.findByTestId('fills-table');
    expect(within(fills).getByText('ZZTRND')).toBeInTheDocument();
    expect(within(fills).getByText('BUY')).toBeInTheDocument();
    expect(screen.queryByTestId('fills-empty')).not.toBeInTheDocument();

    const positions = await screen.findByTestId('execution-positions');
    expect(within(positions).getByText('ZZTRND')).toBeInTheDocument();
    // Seeded at 100 and filled at 100: the unrealized P&L is exactly flat.
    expect(within(positions).getByText('+0.00')).toBeInTheDocument();
  });
});

describe('Market destination handoffs', () => {
  it('"Signals for X" deep-links Research with the instrument filter applied', async () => {
    const user = userEvent.setup();
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);
    await screen.findByRole('region', { name: /intraday/i });

    await user.click(screen.getByRole('button', { name: /signals for ZZTRND/i }));

    expect(window.location.hash).toBe('#/research?instrument=ZZTRND');
  });

  it('daily history swaps the simulated feed for real stored bars, and says so', async () => {
    vi.mocked(apiClient.getPrices).mockResolvedValue({
      total: 2,
      items: [
        { date: '2024-12-30', open: 10, high: 11, low: 9, close: 10.5, volume: 100 },
        { date: '2024-12-31', open: 10.5, high: 11, low: 10, close: 10.8, volume: 120 },
      ] as unknown as apiClient.PriceBar[],
    });
    const user = userEvent.setup();
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);
    const intraday = await screen.findByRole('region', { name: /intraday/i });
    // The default view is the simulated feed, tagged as such.
    expect(within(intraday).getAllByTestId('simulated-tag').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: /daily history/i }));

    const daily = await screen.findByRole('region', { name: /daily history/i });
    expect(apiClient.getPrices).toHaveBeenCalledWith('ZZTRND');
    // The sim tag is visibly replaced by the real-data state.
    expect(within(daily).queryByTestId('simulated-tag')).toBeNull();
    expect(await within(daily).findByTestId('real-data-badge')).toBeInTheDocument();
    expect(within(daily).getByTestId('price-chart')).toBeInTheDocument();
  });

  it('a failed history load is an error with a retry, never an endless loading state', async () => {
    vi.mocked(apiClient.getPrices).mockRejectedValueOnce(new Error('down'));
    const user = userEvent.setup();
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);
    await screen.findByRole('region', { name: /intraday/i });

    await user.click(screen.getByRole('button', { name: /daily history/i }));

    const error = await screen.findByTestId('daily-history-error');
    expect(error).toHaveAttribute('role', 'alert');

    vi.mocked(apiClient.getPrices).mockResolvedValue({
      total: 1,
      items: [
        { date: '2024-12-31', open: 10, high: 11, low: 9, close: 10.5, volume: 100 },
      ] as unknown as apiClient.PriceBar[],
    });
    await user.click(within(error).getByRole('button', { name: /retry/i }));

    const daily = await screen.findByRole('region', { name: /daily history/i });
    expect(await within(daily).findByTestId('price-chart')).toBeInTheDocument();
  });
});
