import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import type { Instrument, PriceBar } from '../../src/api/client';
import { sma } from '../../src/quantlab/data/indicators';
import {
  cellClasses,
  gridClasses,
  parseTickers,
  resample,
  resolveTickers,
  sliceRange,
  tOffset,
} from '../../src/quantlab/market/marketModel';
import { clearBarCache } from '../../src/quantlab/market/useMarketData';
import { MarketView } from '../../src/quantlab/views/MarketView';
import { ThemeProvider } from '../../src/theme/ThemeProvider';
import {
  createdCharts,
  createdMarkerPlugins,
  createdSeries,
  resetLightweightChartsMock,
} from '../mocks/lightweight-charts';
import { installResizeObserver } from '../mocks/resize-observer';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return { ...actual, getPrices: vi.fn(), listInstruments: vi.fn(), listSignals: vi.fn() };
});

installResizeObserver();

// Ten names: more than the eight the old rail could ever show.
const instruments = Array.from({ length: 10 }, (_, i) => ({
  symbol: i === 0 ? 'AAPL.US' : i === 1 ? 'VOD.LON' : `ZZ${i}.US`,
  name: `Company ${i}`,
  currency: 'USD',
  regime_profile: 'mixed',
})) as Instrument[];

/** Weekdays from 2026-01-05 (a Monday), `count` of them. */
function weekdayBars(count: number): PriceBar[] {
  const bars: PriceBar[] = [];
  const day = new Date('2026-01-05T00:00:00Z');
  while (bars.length < count) {
    const dow = day.getUTCDay();
    if (dow !== 0 && dow !== 6) {
      const close = 100 + bars.length;
      bars.push({
        symbol: 'X',
        date: day.toISOString().slice(0, 10),
        open: close - 0.5,
        high: close + 1,
        low: close - 1,
        close,
        volume: 1000,
        source: 'yahoo',
      } as PriceBar);
    }
    day.setUTCDate(day.getUTCDate() + 1);
  }
  return bars;
}

const BARS = weekdayBars(120);

beforeEach(() => {
  window.location.hash = '#/market';
  window.localStorage.clear();
  clearBarCache();
  resetLightweightChartsMock();
  vi.mocked(apiClient.listInstruments).mockResolvedValue({ total: instruments.length, items: instruments });
  vi.mocked(apiClient.getPrices).mockResolvedValue({ total: BARS.length, items: BARS });
  vi.mocked(apiClient.listSignals).mockResolvedValue({
    total: 2,
    items: [
      {
        id: 0,
        symbol: 'AAPL.US',
        // Before any window this test opens: must not land on the first bar.
        date: '2020-01-02',
        rule_name: 'too-old',
        rule_version: '1',
        parameters: {},
        direction: 'bearish',
        trigger_values: {},
        data_window_end: '2020-01-02',
      },
      {
        id: 1,
        symbol: 'AAPL.US',
        date: BARS[BARS.length - 3].date,
        rule_name: 'sma-crossover',
        rule_version: '1',
        parameters: {},
        direction: 'bullish',
        trigger_values: {},
        data_window_end: BARS[BARS.length - 3].date,
      },
    ],
  } as unknown as apiClient.SignalList);
});

function renderMarket() {
  return render(
    <ThemeProvider>
      <MarketView instruments={[]} feedError={null} rng={() => 0.5} />
    </ThemeProvider>,
  );
}

describe('market model', () => {
  it('lays out one chart full, two side by side, three and four in a 2x2', () => {
    expect(gridClasses(1)).toContain('grid-cols-1');
    expect(gridClasses(2)).toContain('lg:grid-cols-2');
    expect(gridClasses(2)).toContain('lg:grid-rows-1');
    expect(gridClasses(4)).toContain('lg:grid-rows-2');
    expect(cellClasses(2, 3)).toBe('lg:col-span-2');
    expect(cellClasses(2, 4)).toBe('');
  });

  it('aggregates daily bars into weekly OHLCV dated by the last session', () => {
    const weekly = resample(BARS.slice(0, 10), '1W');

    expect(weekly).toHaveLength(2);
    expect(weekly[0]).toMatchObject({
      date: '2026-01-09',
      open: BARS[0].open,
      high: BARS[4].high,
      low: BARS[0].low,
      close: BARS[4].close,
      volume: 5000,
    });
    // The source is not mutated.
    expect(BARS[0].date).toBe('2026-01-05');
  });

  it('cuts a range back from the latest bar, not from today', () => {
    const last = BARS[BARS.length - 1].date;
    const month = sliceRange(BARS, '1M');

    expect(month[month.length - 1].date).toBe(last);
    expect(month.length).toBeGreaterThan(18);
    expect(month.length).toBeLessThan(25);
    expect(sliceRange(BARS, 'ALL')).toHaveLength(BARS.length);
  });

  it('labels the latest bar T-0 and counts back from it', () => {
    expect(tOffset(9, 10)).toBe('T-0');
    expect(tOffset(0, 10)).toBe('T-9');
  });

  it('parses typed tickers and resolves a bare root to its only listing', () => {
    expect(parseTickers('aapl, vod.lon  NOPE <GO>')).toEqual(['AAPL', 'VOD.LON', 'NOPE']);
    expect(resolveTickers(['AAPL', 'VOD.LON', 'NOPE'], ['AAPL.US', 'VOD.LON'])).toEqual({
      found: ['AAPL.US', 'VOD.LON'],
      unknown: ['NOPE'],
    });
  });

  it('computes a simple moving average with a null warm-up', () => {
    expect(sma([1, 2, 3, 4], 2)).toEqual([null, 1.5, 2.5, 3.5]);
  });
});

describe('Market view', () => {
  it('asks for a ticker instead of charting one unasked', async () => {
    renderMarket();

    const empty = await screen.findByTestId('market-no-selection');
    expect(empty).toHaveTextContent(/select a ticker to review market movements/i);
    expect(screen.queryByTestId('market-grid')).toBeNull();
  });

  it('lists the whole catalogue, not an eight-name watchlist', async () => {
    renderMarket();

    const list = await screen.findByTestId('universe-list');
    expect(within(list).getAllByRole('checkbox')).toHaveLength(10);
  });

  it('charts one ticker full width, then two side by side', async () => {
    const user = userEvent.setup();
    renderMarket();
    const list = await screen.findByTestId('universe-list');

    await user.click(within(list).getByRole('checkbox', { name: /AAPL\.US/ }));
    let grid = await screen.findByTestId('market-grid');
    expect(grid).toHaveAttribute('data-count', '1');
    expect(grid).toHaveClass('grid-cols-1');
    expect(window.location.hash).toContain('symbols=AAPL.US');

    await user.click(within(list).getByRole('checkbox', { name: /VOD\.LON/ }));
    grid = screen.getByTestId('market-grid');
    expect(grid).toHaveAttribute('data-count', '2');
    expect(grid).toHaveClass('lg:grid-cols-2');
    expect(within(grid).getAllByTestId('market-cell')).toHaveLength(2);
  });

  it('caps the charts at four and disables the rest of the list', async () => {
    const user = userEvent.setup();
    renderMarket();
    const list = await screen.findByTestId('universe-list');
    const boxes = within(list).getAllByRole('checkbox');

    for (const box of boxes.slice(0, 4)) await user.click(box);

    expect(screen.getByTestId('market-grid')).toHaveAttribute('data-count', '4');
    expect(screen.getByTestId('market-grid')).toHaveClass('lg:grid-rows-2');
    expect(screen.getByTestId('charted-count')).toHaveTextContent('4/4');
    expect(boxes[4]).toBeDisabled();

    // Removing one frees a slot.
    await user.click(screen.getByRole('button', { name: /remove AAPL\.US from the charts/i }));
    expect(screen.getByTestId('market-grid')).toHaveAttribute('data-count', '3');
    expect(boxes[4]).toBeEnabled();
  });

  it('charts typed tickers on GO and names the ones it could not find', async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByTestId('universe-list');

    await user.type(screen.getByTestId('market-command'), 'aapl vod.lon NOPE{Enter}');

    expect(screen.getByTestId('market-grid')).toHaveAttribute('data-count', '2');
    expect(screen.getByTestId('market-command-feedback')).toHaveTextContent('Not found: NOPE');
  });

  it('says on the chart what a bar is, which dates it covers and how old it is', async () => {
    window.location.hash = '#/market?symbols=AAPL.US';
    renderMarket();

    const card = await screen.findByRole('region', { name: /AAPL\.US · Company 0/ });
    await within(card).findByTestId('market-chart');
    const last = BARS[BARS.length - 1].date;

    expect(within(card).getByTestId('provenance-historical')).toHaveTextContent(/historical/i);
    expect(within(card).queryByTestId('simulated-tag')).toBeNull();
    // Named for the provider that supplied the bars, not for where they are stored.
    expect(within(card).getByTestId('fact-source')).toHaveTextContent('Yahoo Finance (ingested EOD)');
    expect(within(card).getByTestId('fact-bar')).toHaveTextContent('1 trading day');
    expect(within(card).getByTestId('fact-window')).toHaveTextContent(`→ ${last}`);
    expect(within(card).getByTestId('fact-latest')).toHaveTextContent(new RegExp(`${last} · \\d+ days? old|today`));
    // The readout is on without a hover: latest bar, its weekday and T-0.
    expect(within(card).getByTestId('readout-date')).toHaveTextContent(last);
    expect(within(card).getByTestId('readout-offset')).toHaveTextContent('T-0');
    expect(screen.getByTestId('market-provenance')).toHaveTextContent(/historical .* not real-time/i);
  });

  it('splits the source by provider when a window mixes them', async () => {
    const mixed = BARS.map((bar, i) => ({ ...bar, source: i >= BARS.length - 5 ? 'tiingo' : 'yahoo' }));
    vi.mocked(apiClient.getPrices).mockResolvedValue({ total: mixed.length, items: mixed });
    window.location.hash = '#/market?symbols=AAPL.US&range=1M';
    renderMarket();
    const card = await screen.findByRole('region', { name: /AAPL\.US/ });
    await within(card).findByTestId('market-chart');

    expect(within(card).getByTestId('fact-source')).toHaveTextContent(/Yahoo Finance \d+ · Tiingo 5 \(ingested EOD\)/);
  });

  it('flags generated bars as synthetic instead of historical', async () => {
    const generated = BARS.map((bar) => ({ ...bar, source: 'synthetic' }));
    vi.mocked(apiClient.getPrices).mockResolvedValue({ total: generated.length, items: generated });
    window.location.hash = '#/market?symbols=AAPL.US';
    renderMarket();
    const card = await screen.findByRole('region', { name: /AAPL\.US/ });
    await within(card).findByTestId('market-chart');

    expect(within(card).getByTestId('provenance-synthetic')).toHaveTextContent(/synthetic/i);
    expect(within(card).queryByTestId('provenance-historical')).toBeNull();
    expect(within(card).getByTestId('fact-source')).toHaveTextContent('Synthetic (generated, not market data)');
  });

  it('says so when an older backend does not report the provider', async () => {
    const bare = BARS.map((bar) => {
      const copy: Partial<PriceBar> = { ...bar };
      delete copy.source;
      return copy as PriceBar;
    });
    vi.mocked(apiClient.getPrices).mockResolvedValue({ total: bare.length, items: bare });
    window.location.hash = '#/market?symbols=AAPL.US';
    renderMarket();
    const card = await screen.findByRole('region', { name: /AAPL\.US/ });
    await within(card).findByTestId('market-chart');

    expect(within(card).getByTestId('fact-source')).toHaveTextContent('provider not reported');
  });

  it('switches the bar size and says the bars are aggregated', async () => {
    window.location.hash = '#/market?symbols=AAPL.US&range=ALL';
    const user = userEvent.setup();
    renderMarket();
    const card = await screen.findByRole('region', { name: /AAPL\.US/ });
    await within(card).findByTestId('market-chart');

    await user.click(screen.getByRole('button', { name: '1W' }));

    expect(within(card).getByTestId('fact-bar')).toHaveTextContent('1 week (from daily)');
    expect(within(card).getByTestId('fact-count')).toHaveTextContent('24');
    const candles = createdSeries.filter((s) => s.seriesType === 'Candlestick').at(-1)!;
    expect(candles.setData.mock.calls.at(-1)![0]).toHaveLength(24);
  });

  it('draws added studies on the same chart: overlays on price, oscillators in panes', async () => {
    window.location.hash = '#/market?symbols=AAPL.US&studies=sma20,rsi,macd';
    renderMarket();
    const card = await screen.findByRole('region', { name: /AAPL\.US/ });
    await within(card).findByTestId('market-chart');

    // One chart per card, however many studies are on.
    expect(createdCharts).toHaveLength(1);
    const lines = createdSeries.filter((s) => s.seriesType === 'Line');
    // SMA on the price pane, RSI in the first pane below, MACD + signal in the next.
    expect(lines.filter((s) => s.paneIndex === 0)).toHaveLength(1);
    expect(lines.find((s) => s.options.title === 'RSI14')?.paneIndex).toBe(1);
    expect(lines.filter((s) => s.paneIndex === 2)).toHaveLength(2);

    const legend = within(card).getByTestId('chart-legend');
    expect(legend).toHaveTextContent('SMA 20');
    expect(legend).toHaveTextContent('RSI 14');
  });

  it('toggles a study from the toolbar and keeps it in the address', async () => {
    window.location.hash = '#/market?symbols=AAPL.US';
    const user = userEvent.setup();
    renderMarket();
    await screen.findByTestId('market-chart');

    await user.click(screen.getByRole('button', { name: 'SMA 50' }));

    expect(window.location.hash).toContain('studies=sma50');
    expect(await screen.findByTestId('chart-legend')).toHaveTextContent('SMA 50');
  });

  it('marks the models\' signals on the bars they fired on', async () => {
    window.location.hash = '#/market?symbols=AAPL.US&studies=signals';
    renderMarket();
    await screen.findByTestId('market-chart');

    expect(apiClient.listSignals).toHaveBeenCalledWith(expect.objectContaining({ instrument: 'AAPL.US' }));
    await vi.waitFor(() => {
      const markers = createdMarkerPlugins.at(-1)!.setMarkers.mock.calls.at(-1)![0];
      expect(markers).toEqual([
        expect.objectContaining({ time: BARS[BARS.length - 3].date, id: 'sma-crossover', shape: 'arrowUp' }),
      ]);
    });
  });

  it('labels the simulation as not market data, everywhere it shows', async () => {
    window.location.hash = '#/market?symbols=AAPL.US&data=sim';
    renderMarket();

    const card = await screen.findByRole('region', { name: /AAPL\.US/ });
    const chart = await within(card).findByTestId('market-chart');
    expect(chart).toHaveAttribute('data-mode', 'simulated');
    expect(within(card).getByTestId('simulated-tag')).toBeInTheDocument();
    expect(within(card).queryByTestId('provenance-historical')).toBeNull();
    expect(within(card).getByTestId('fact-source')).toHaveTextContent(/not market data/i);
    expect(screen.getByTestId('market-provenance')).toHaveAttribute('data-mode', 'simulated');
    expect(screen.getByTestId('market-provenance')).toHaveTextContent(/no live feed/i);
    // Bar size belongs to historical data only.
    expect(screen.getByRole('button', { name: '1W' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Model signals' })).toBeDisabled();
    // The chart's time axis shows clock time, not dates.
    expect(createdCharts.at(-1)!.options).toMatchObject({ timeScale: expect.objectContaining({ secondsVisible: true }) });
  });

  it('saves a custom universe and filters the list to it', async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByTestId('universe-list');

    await user.click(screen.getByRole('button', { name: /new custom list/i }));
    await user.type(screen.getByRole('textbox', { name: 'List name' }), 'Mine');
    await user.type(screen.getByRole('textbox', { name: 'Tickers' }), 'AAPL VOD.LON');
    await user.click(screen.getByRole('button', { name: 'Save list' }));

    expect(screen.getByTestId('market-universe')).toHaveValue('custom:Mine');
    expect(within(screen.getByTestId('universe-list')).getAllByRole('checkbox')).toHaveLength(2);
    expect(JSON.parse(window.localStorage.getItem('quantlab.market.universes')!)).toEqual([
      { name: 'Mine', symbols: ['AAPL.US', 'VOD.LON'] },
    ]);
  });

  it('explains a catalogue it cannot read', async () => {
    vi.mocked(apiClient.listInstruments).mockRejectedValue(new Error('backend down'));
    await act(async () => {
      renderMarket();
    });

    expect(await screen.findByTestId('market-error')).toHaveAttribute('role', 'alert');
  });
});
