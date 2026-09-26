import { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';
import type { PriceBar } from '../api/client';
import { token } from '../lib/token';
import { useTheme } from '../theme/ThemeProvider';
import { usePanelSize } from './usePanelSize';

/** A model's signal, drawn on the bar it fired on. */
export interface ChartSignal {
  date: string;
  direction: 'bullish' | 'bearish';
  /** Short text beside the arrow, so several models can share one chart. */
  label: string;
}

interface CandlestickChartProps {
  bars: PriceBar[];
  markerDate?: string;
  /** Model signals: bullish below the bar pointing up, bearish above pointing down. */
  signals?: ChartSignal[];
  /**
   * Size from container observation instead of dock-panel events. Only safe
   * outside the dock — see the note at the creation site (FR-009).
   */
  autoSize?: boolean;
}

interface HoverReadout {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// Canvas needs literal colours, so the chart reads the live design tokens off
// its own container — the same approach the Quant Lab charts use — rather than
// mirroring the palette as hex. Up/down candles are the accent/destructive
// tokens: green plays no part in this grammar.
function readPalette(host: Element | null) {
  return {
    background: token(host, '--card'),
    text: token(host, '--muted-foreground'),
    grid: token(host, '--grid'),
    border: token(host, '--border'),
    up: token(host, '--primary'),
    down: token(host, '--destructive'),
    volume: token(host, '--muted-foreground', 0.35),
    marker: token(host, '--primary'),
  };
}

function toCandle(bar: PriceBar): CandlestickData<Time> {
  return {
    time: bar.date as Time,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  };
}

function toVolume(bar: PriceBar, color: string): HistogramData<Time> {
  return { time: bar.date as Time, value: bar.volume, color };
}

type Ohlc = Pick<CandlestickData<Time>, 'open' | 'high' | 'low' | 'close'>;

function isOhlc(data: unknown): data is Ohlc {
  if (typeof data !== 'object' || data === null) return false;
  const point = data as Record<string, unknown>;
  return (
    typeof point.open === 'number' &&
    typeof point.high === 'number' &&
    typeof point.low === 'number' &&
    typeof point.close === 'number'
  );
}

function isVolumePoint(data: unknown): data is { value: number } {
  return (
    typeof data === 'object' &&
    data !== null &&
    typeof (data as { value?: unknown }).value === 'number'
  );
}

const NO_SIGNALS: ChartSignal[] = [];

export function CandlestickChart({
  bars,
  markerDate,
  signals = NO_SIGNALS,
  autoSize = false,
}: CandlestickChartProps) {
  const { theme } = useTheme();
  const { width, height, isVisible } = usePanelSize();

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const [hover, setHover] = useState<HoverReadout | null>(null);

  const hasBars = bars.length > 0;
  const markedBar = markerDate ? bars.find((bar) => bar.date === markerDate) : undefined;

  useEffect(() => {
    if (!hasBars) return;
    const container = containerRef.current;
    if (!container) return;

    const colors = readPalette(container);
    const chart = createChart(container, {
      // autoSize only outside the dock: a panel in an inactive tab has no
      // measurable box, so container observation yields a zero-height chart
      // and dock panels are sized explicitly from the panel's own events
      // instead (FR-009).
      autoSize,
      layout: {
        background: { type: ColorType.Solid, color: colors.background },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border, timeVisible: false },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
      borderVisible: false,
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: colors.volume,
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    const markers = createSeriesMarkers(candleSeries, []);

    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      const candle = param.time ? param.seriesData.get(candleSeries) : undefined;
      if (!isOhlc(candle)) {
        setHover(null);
        return;
      }
      const volumePoint = param.seriesData.get(volumeSeries);
      setHover({
        date: String(param.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
        volume: isVolumePoint(volumePoint) ? volumePoint.value : 0,
      });
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    markersRef.current = markers;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      markersRef.current = null;
      setHover(null);
    };
    // The chart is created once per mount; theme changes repaint it in place below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasBars]);

  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    const markers = markersRef.current;
    if (!candleSeries || !volumeSeries || !markers) return;

    const colors = readPalette(containerRef.current);
    candleSeries.setData(bars.map(toCandle));
    volumeSeries.setData(bars.map((bar) => toVolume(bar, colors.volume)));

    const marker: SeriesMarker<Time>[] = markedBar
      ? [
          {
            time: markedBar.date as Time,
            position: 'aboveBar',
            shape: 'arrowDown',
            color: colors.marker,
            text: 'signal',
          },
        ]
      : [];
    // Only signals on a bar the chart has: a marker on a date outside the
    // series makes lightweight-charts throw.
    const onChart = new Set(bars.map((bar) => bar.date));
    for (const signal of signals) {
      if (!onChart.has(signal.date)) continue;
      const bullish = signal.direction === 'bullish';
      marker.push({
        time: signal.date as Time,
        position: bullish ? 'belowBar' : 'aboveBar',
        shape: bullish ? 'arrowUp' : 'arrowDown',
        color: bullish ? colors.up : colors.down,
        text: signal.label,
      });
    }
    // The plugin wants markers in time order.
    marker.sort((a, b) => String(a.time).localeCompare(String(b.time)));
    markers.setMarkers(marker);

    // Without this the chart shows only the rightmost slice that fits in the
    // viewport. A ten-year window then looks like "only 2016 data" even though
    // the series reaches back further.
    chartRef.current?.timeScale().fitContent();
  }, [bars, markedBar, signals, theme]);

  // Apply the panel's size, but only while the panel is actually visible. A
  // hidden panel reports a box we must not draw to; on the hidden -> visible
  // transition this effect re-runs and applies the current size once, which is
  // what keeps a revealed background tab from showing a blank chart (FR-009).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || autoSize || !isVisible) return;
    if (width <= 0 || height <= 0) return;
    chart.resize(width, height);
  }, [width, height, isVisible, autoSize]);

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!chart || !candleSeries || !volumeSeries) return;

    const palette = readPalette(containerRef.current);
    chart.applyOptions({
      layout: {
        background: { type: ColorType.Solid, color: palette.background },
        textColor: palette.text,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border },
    });
    candleSeries.applyOptions({
      upColor: palette.up,
      downColor: palette.down,
      wickUpColor: palette.up,
      wickDownColor: palette.down,
    });
    volumeSeries.applyOptions({ color: palette.volume });
    // `theme` is the trigger: the palette itself is read live above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  if (!hasBars) {
    return (
      <p className="rounded-sm border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
        No price history available.
      </p>
    );
  }

  return (
    <div className="relative h-full">
      <div
        ref={containerRef}
        data-testid="price-chart"
        className="h-full min-h-[320px] w-full overflow-hidden rounded-sm border border-border"
      />
      {markedBar && (
        <span data-testid="signal-marker" className="sr-only">
          Signal marked on {markedBar.date}
        </span>
      )}
      {signals.length > 0 && (
        <span data-testid="chart-signal-count" className="sr-only">
          {signals.length} model signals marked on the chart
        </span>
      )}
      {hover && (
        <div className="pointer-events-none absolute left-3 top-3 rounded-sm border border-border bg-card/95 px-3 py-2 font-mono text-[11px] tabular-nums text-card-foreground">
          <div>{hover.date}</div>
          <div className="mt-1 flex gap-2">
            <span>O {hover.open.toFixed(2)}</span>
            <span>H {hover.high.toFixed(2)}</span>
            <span>L {hover.low.toFixed(2)}</span>
            <span>C {hover.close.toFixed(2)}</span>
          </div>
          <div className="mt-0.5 text-muted-foreground">Vol {hover.volume.toLocaleString()}</div>
        </div>
      )}
    </div>
  );
}
