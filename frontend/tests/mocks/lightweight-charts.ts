import { vi } from 'vitest';

/**
 * Hand-written fake of the `lightweight-charts` v5 API surface this app uses.
 * Registered globally in tests/setup.ts via `vi.mock('lightweight-charts', ...)`,
 * since the real library draws to <canvas>, which jsdom does not implement
 * (see research.md's "testing a canvas-based chart under jsdom" decision).
 *
 * Tests import the arrays below directly (not through 'lightweight-charts') to
 * inspect what CandlestickChart did, since both resolve to this same module.
 */

export const CandlestickSeries = { seriesType: 'Candlestick' } as const;
export const HistogramSeries = { seriesType: 'Histogram' } as const;
export const LineSeries = { seriesType: 'Line' } as const;

export const LineStyle = { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3, SparseDotted: 4 } as const;

export const ColorType = { Solid: 'solid', VerticalGradient: 'gradient' } as const;
export const CrosshairMode = { Normal: 0, Magnet: 1 } as const;

export type MockSeriesDefinition =
  | typeof CandlestickSeries
  | typeof HistogramSeries
  | typeof LineSeries;

export interface MockSeries {
  seriesType: MockSeriesDefinition['seriesType'];
  setData: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  priceScale: ReturnType<typeof vi.fn>;
  createPriceLine: ReturnType<typeof vi.fn>;
  /** The pane the series was added to; 0 is the price pane. */
  paneIndex: number;
  options: Record<string, unknown>;
}

export interface MockMarkersPlugin {
  series: MockSeries;
  setMarkers: ReturnType<typeof vi.fn>;
}

export interface MockChart {
  addSeries: ReturnType<typeof vi.fn>;
  subscribeCrosshairMove: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  timeScale: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  panes: ReturnType<typeof vi.fn>;
  options: Record<string, unknown>;
}

export const createdCharts: MockChart[] = [];
export const createdSeries: MockSeries[] = [];
export const createdMarkerPlugins: MockMarkersPlugin[] = [];

export function resetLightweightChartsMock() {
  createdCharts.length = 0;
  createdSeries.length = 0;
  createdMarkerPlugins.length = 0;
}

function makeSeries(
  definition: MockSeriesDefinition,
  options: Record<string, unknown> = {},
  paneIndex = 0,
): MockSeries {
  const series: MockSeries = {
    seriesType: definition.seriesType,
    setData: vi.fn(),
    applyOptions: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    createPriceLine: vi.fn(),
    paneIndex,
    options,
  };
  createdSeries.push(series);
  return series;
}

export function createChart(_container?: unknown, options: Record<string, unknown> = {}): MockChart {
  const chart: MockChart = {
    addSeries: vi.fn(
      (definition: MockSeriesDefinition, seriesOptions?: Record<string, unknown>, paneIndex?: number) =>
        makeSeries(definition, seriesOptions, paneIndex),
    ),
    panes: vi.fn(() => []),
    options,
    subscribeCrosshairMove: vi.fn(),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn(), applyOptions: vi.fn() })),
    resize: vi.fn(),
    remove: vi.fn(),
  };
  createdCharts.push(chart);
  return chart;
}

export function createSeriesMarkers(series: MockSeries, initialMarkers: unknown[] = []) {
  const plugin: MockMarkersPlugin = { series, setMarkers: vi.fn() };
  void initialMarkers;
  createdMarkerPlugins.push(plugin);
  return plugin;
}
