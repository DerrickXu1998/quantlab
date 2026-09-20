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
    // Two regions only: the instruments rail and the price chart itself.
    expect(screen.getAllByRole('region').map((region) => region.getAttribute('aria-label')))
      .toEqual(['Instruments', expect.stringMatching(/intraday/i)]);
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
});

/**
 * Fitting, as a behaviour.
 *
 * Every fault these cover was invisible in the source and obvious in a
 * browser: an order book sliced through its last bid, a price panel stopping
 * 380px short of the bottom of the viewport, a row with its price against one
 * edge of the screen and its size against the other. jsdom has no layout, so
 * these assert the contract the layout primitives encode — the flex, scroll
 * and measure classes that decide whether a boundary is a scroll edge or a
 * half-rendered number.
 */
describe('workspace fitting', () => {
  const hasAll = (element: Element | null | undefined, ...classes: string[]) =>
    classes.filter((name) => !element?.classList.contains(name));

  it('scrolls the order book rather than clipping it mid-row', async () => {
    renderWithFeed(<ExecutionView instruments={instruments} feedError={null} />);
    const book = await screen.findByTestId('order-book');

    const region = book.parentElement;
    expect(region).toHaveClass('overflow-y-auto');
    // min-h-0 is the part everyone forgets: without it the overflow escapes
    // the box instead of scrolling inside it.
    expect(hasAll(region, 'min-h-0', 'flex-1')).toEqual([]);

    // min-h-full, never h-full — the book spreads into a tall panel and
    // scrolls out of a short one, and either way no row is sliced.
    expect(book).toHaveClass('min-h-full');
    expect(book).not.toHaveClass('h-full');
  });

  it('holds the book to a reading measure instead of the full panel width', async () => {
    renderWithFeed(<ExecutionView instruments={instruments} feedError={null} />);
    const book = await screen.findByTestId('order-book');

    const measure = book.firstElementChild;
    expect(measure).toHaveClass('mx-auto');
    expect(measure?.className).toMatch(/max-w-\[\d/);
    // Everything is inside it, so no level's price and size can end up at
    // opposite edges of a 1120px panel.
    expect(measure?.contains(screen.getByTestId('order-book-spread'))).toBe(true);
    // One depth bar per level: every one of the twenty is inside the measure.
    expect(measure?.querySelectorAll('[aria-hidden="true"]').length).toBe(20);
  });

  it('fills every execution panel so no cell leaves a band of bare background', async () => {
    renderWithFeed(<ExecutionView instruments={instruments} feedError={null} />);
    await screen.findByTestId('order-book');

    for (const name of ['Order ticket', 'Recent fills', 'Positions']) {
      const panel = screen.getByRole('region', { name });
      expect(hasAll(panel, 'flex', 'min-h-0', 'flex-1', 'flex-col')).toEqual([]);
    }
  });

  it('keeps the fills and positions absences compact, so the book takes the slack', async () => {
    renderWithFeed(<ExecutionView instruments={instruments} feedError={null} />);
    await screen.findByTestId('order-book');

    // Still explained, just not a 180px band of nothing.
    expect(screen.getByTestId('fills-empty')).toHaveTextContent(/no fills yet/i);
    expect(screen.getByTestId('fills-empty')).toHaveClass('py-6');
    expect(screen.getByTestId('execution-positions-empty')).toHaveClass('py-6');
  });

  it('makes the market workspace a fill column and grows the chart into it', async () => {
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);
    const panel = await screen.findByRole('region', { name: /intraday/i });

    const workspace = screen.getByTestId('market-workspace');
    expect(hasAll(workspace, 'min-h-0', 'flex-1', 'overflow-y-auto')).toEqual([]);
    expect(hasAll(panel, 'flex', 'min-h-0', 'flex-1', 'flex-col')).toEqual([]);

    // The chart grows through PriceChart's own `fill` prop now, rather than a
    // wrapper reaching through its DOM with arbitrary variants. Assert the
    // shape that produces: the canvas wrapper is a growing flex child with a
    // floor, and carries no inline pixel height to fight.
    const summary = within(panel).getByTestId('price-chart-summary');
    const wrapper = summary.parentElement as HTMLElement;
    expect(hasAll(wrapper, 'min-h-[220px]', 'flex-1')).toEqual([]);
    expect(wrapper.style.height).toBe('');

    const column = wrapper.parentElement;
    expect(hasAll(column, 'flex', 'min-h-0', 'flex-1', 'flex-col')).toEqual([]);
  });

  it('gives the chart the space a toggled-off indicator is not using', async () => {
    const user = userEvent.setup();
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);
    const panel = await screen.findByRole('region', { name: /intraday/i });
    const cell = panel.parentElement;

    // With every indicator off there is no void below the chart: the chart is
    // the one thing in the column that grows.
    expect(hasAll(cell, 'flex-1', 'flex', 'flex-col')).toEqual([]);

    await user.click(screen.getByRole('button', { name: /^RSI 14/ }));
    const rsi = screen.getByRole('region', { name: /^RSI \(14\)/ });

    // The sub-panel takes its own height and no more; the chart keeps the rest.
    expect(rsi.parentElement).toHaveClass('shrink-0');
    expect(hasAll(cell, 'flex-1')).toEqual([]);
  });

  it('fills the instrument rail and lets a name read at 240px', async () => {
    renderWithFeed(<IndicatorsView instruments={instruments} feedError={null} />);
    await screen.findByRole('region', { name: /intraday/i });

    const rail = screen.getByRole('region', { name: 'Instruments' });
    expect(hasAll(rail, 'flex', 'min-h-0', 'flex-1', 'flex-col')).toEqual([]);

    const row = within(rail).getByRole('button', { name: /ZZTRND/ });
    // Two lines: identifiers over movement. On one line the name was the only
    // non-numeric thing competing for 240px, and it always lost.
    expect(row).toHaveClass('flex-col');
    expect(row).toHaveAttribute('title', 'Trend Co');
    expect(row).toHaveTextContent('Trend Co');
  });
});
