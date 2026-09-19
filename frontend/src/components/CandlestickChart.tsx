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
import { useTheme } from '../theme/ThemeProvider';
import { usePanelSize } from './usePanelSize';

interface CandlestickChartProps {
  bars: PriceBar[];
  markerDate?: string;
}

interface HoverReadout {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// Chart colors can't come from CSS variables — the canvas needs literal values —
// so the two palettes are mirrored here from the tokens in styles.css.
const PALETTES = {
  light: {
    background: '#ffffff',
    text: '#334155',
    grid: '#e8edf3',
    border: '#dde3ea',
    up: '#16a34a',
    down: '#dc2626',
    volume: '#cbd5e1',
    marker: '#dc2626',
  },
  dark: {
    background: '#1b2130',
    text: '#cbd5e1',
    grid: '#2b3444',
    border: '#3a4457',
    up: '#3fb950',
    down: '#f0605a',
    volume: '#46536b',
    marker: '#f0605a',
  },
} as const;

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

export function CandlestickChart({ bars, markerDate }: CandlestickChartProps) {
  const { theme } = useTheme();
  const palette = PALETTES[theme];
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

    const colors = PALETTES[theme];
    const chart = createChart(container, {
      // No autoSize: a panel in an inactive tab has no measurable box, so
      // container observation yields a zero-height chart. Sizing is driven
      // explicitly from the dock panel's own events instead (FR-009).
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

    candleSeries.setData(bars.map(toCandle));
    volumeSeries.setData(bars.map((bar) => toVolume(bar, palette.volume)));

    const marker: SeriesMarker<Time>[] = markedBar
      ? [
          {
            time: markedBar.date as Time,
            position: 'aboveBar',
            shape: 'arrowDown',
            color: palette.marker,
            text: 'signal',
          },
        ]
      : [];
    markers.setMarkers(marker);
  }, [bars, markedBar, palette.marker, palette.volume]);

  // Apply the panel's size, but only while the panel is actually visible. A
  // hidden panel reports a box we must not draw to; on the hidden -> visible
  // transition this effect re-runs and applies the current size once, which is
  // what keeps a revealed background tab from showing a blank chart (FR-009).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !isVisible) return;
    if (width <= 0 || height <= 0) return;
    chart.resize(width, height);
  }, [width, height, isVisible]);

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!chart || !candleSeries || !volumeSeries) return;

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
  }, [palette]);

  if (!hasBars) {
    return (
      <p className="rounded-lg border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
        No price history available.
      </p>
    );
  }

  return (
    <div className="relative">
      <div
        ref={containerRef}
        data-testid="price-chart"
        className="h-[320px] w-full overflow-hidden rounded-lg border border-border"
      />
      {markedBar && (
        <span data-testid="signal-marker" className="sr-only">
          Signal marked on {markedBar.date}
        </span>
      )}
      {hover && (
        <div className="pointer-events-none absolute left-3 top-3 rounded-md border border-border bg-card/95 px-3 py-2 text-xs tabular-nums text-card-foreground shadow-sm">
          <div className="font-semibold">{hover.date}</div>
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
