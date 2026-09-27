import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { PriceBar } from '../../api/client';
import type { ChartSignal } from '../../components/CandlestickChart';
import { token } from '../../lib/token';
import { cn } from '../../lib/utils';
import { useTheme } from '../../theme/ThemeProvider';
import { RSI_PERIOD } from '../data/indicators';
import {
  INTERVAL_NOUN,
  STUDIES,
  tOffset,
  weekday,
  type DataMode,
  type Interval,
  type StudyId,
  type Studies,
} from './marketModel';
import type { SimPoint } from './useMarketData';

/**
 * How each overlay is drawn. The palette has one accent and one loss colour,
 * so overlays are told apart by tone *and* dash -- the legend repeats the dash
 * so the line on the chart and its name in the readout always match.
 */
type Tone = 'foreground' | 'muted' | 'primary';

interface LineLook {
  tone: Tone;
  style: LineStyle;
  width: 1 | 2;
}

const LOOK: Record<'sma20' | 'sma50' | 'ema20' | 'bbMid' | 'bbBand' | 'vwap' | 'rsi' | 'macd' | 'macdSignal', LineLook> = {
  sma20: { tone: 'foreground', style: LineStyle.Solid, width: 1 },
  sma50: { tone: 'muted', style: LineStyle.Solid, width: 2 },
  ema20: { tone: 'foreground', style: LineStyle.Dashed, width: 1 },
  bbMid: { tone: 'muted', style: LineStyle.SparseDotted, width: 1 },
  bbBand: { tone: 'muted', style: LineStyle.Dotted, width: 1 },
  vwap: { tone: 'primary', style: LineStyle.LargeDashed, width: 1 },
  rsi: { tone: 'primary', style: LineStyle.Solid, width: 1 },
  macd: { tone: 'foreground', style: LineStyle.Solid, width: 1 },
  macdSignal: { tone: 'muted', style: LineStyle.Dashed, width: 1 },
};

const DASH: Record<number, string | undefined> = {
  [LineStyle.Solid]: undefined,
  [LineStyle.Dotted]: '1 2',
  [LineStyle.Dashed]: '4 2',
  [LineStyle.LargeDashed]: '6 3',
  [LineStyle.SparseDotted]: '1 4',
};

const TONE_CLASS: Record<Tone, string> = {
  foreground: 'text-foreground',
  muted: 'text-muted-foreground',
  primary: 'text-primary',
};

function Swatch({ look }: { look: LineLook }) {
  return (
    <svg width="16" height="6" aria-hidden="true" className={cn('shrink-0', TONE_CLASS[look.tone])}>
      <line
        x1="0"
        y1="3"
        x2="16"
        y2="3"
        stroke="currentColor"
        strokeWidth={look.width === 2 ? 2 : 1.5}
        strokeDasharray={DASH[look.style]}
      />
    </svg>
  );
}

function readPalette(host: Element | null) {
  return {
    background: token(host, '--card'),
    text: token(host, '--muted-foreground'),
    grid: token(host, '--grid'),
    border: token(host, '--border'),
    up: token(host, '--primary'),
    down: token(host, '--destructive'),
    volume: token(host, '--muted-foreground', 0.3),
    foreground: token(host, '--foreground', 0.85),
    muted: token(host, '--muted-foreground'),
    primary: token(host, '--primary'),
    upSoft: token(host, '--primary', 0.5),
    downSoft: token(host, '--destructive', 0.5),
  };
}

type Palette = ReturnType<typeof readPalette>;

function lineOptions(palette: Palette, look: LineLook) {
  return {
    color: palette[look.tone],
    lineWidth: look.width,
    lineStyle: look.style,
    // Named in the readout legend, not on the price axis, where five overlay
    // labels stacked into an unreadable column.
    title: '',
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  };
}

function toLine(times: Time[], values: (number | null)[] | undefined) {
  if (!values) return [];
  const out: { time: Time; value: number }[] = [];
  values.forEach((value, index) => {
    if (value !== null && Number.isFinite(value) && times[index] !== undefined) {
      out.push({ time: times[index], value });
    }
  });
  return out;
}

export interface MarketChartProps {
  mode: DataMode;
  symbol: string;
  /** Historical bars, already aggregated to `interval` and cut to the range. */
  bars?: PriceBar[];
  /** The simulated walk, one point per second. */
  sim?: SimPoint[];
  /** Studies aligned index-for-index with `bars` or `sim`. */
  studies: Studies;
  active: ReadonlySet<StudyId>;
  signals?: ChartSignal[];
  interval: Interval;
  /** Changes when the view should re-fit (symbol, range, interval, mode). */
  fitKey: string;
}

const NO_SIGNALS: ChartSignal[] = [];

function fmt(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function clockTime(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(11, 19);
}

export function MarketChart({
  mode,
  symbol,
  bars = [],
  sim = [],
  studies,
  active,
  signals = NO_SIGNALS,
  interval,
  fitKey,
}: MarketChartProps) {
  const { theme } = useTheme();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<Map<string, ISeriesApi<SeriesType>>>(new Map());
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const fittedRef = useRef<string | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const historical = mode === 'historical';
  const length = historical ? bars.length : sim.length;
  const hasData = length > 0;

  const times = useMemo<Time[]>(
    () =>
      historical
        ? bars.map((bar) => bar.date as Time)
        : sim.map((point) => point.time as UTCTimestamp),
    [historical, bars, sim],
  );
  const indexOf = useMemo(() => {
    const map = new Map<string, number>();
    times.forEach((time, index) => map.set(String(time), index));
    return map;
  }, [times]);
  const indexRef = useRef(indexOf);
  indexRef.current = indexOf;

  const showRsi = active.has('rsi');
  const showMacd = active.has('macd');
  // Which series exist is structural: the chart is rebuilt when it changes,
  // and only the data is pushed on every tick.
  const structure = [mode, ...STUDIES.filter((s) => active.has(s.id)).map((s) => s.id)].join('|');

  useEffect(() => {
    if (!hasData) return;
    const container = containerRef.current;
    if (!container) return;
    const palette = readPalette(container);

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: palette.background },
        textColor: palette.text,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: 11,
        panes: { separatorColor: palette.border },
      },
      localization: { dateFormat: 'yyyy-MM-dd' },
      grid: { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: palette.border },
      timeScale: {
        borderColor: palette.border,
        timeVisible: !historical,
        secondsVisible: !historical,
        rightOffset: 2,
      },
    });

    const series = new Map<string, ISeriesApi<SeriesType>>();
    const main = historical
      ? chart.addSeries(CandlestickSeries, {
          upColor: palette.up,
          downColor: palette.down,
          wickUpColor: palette.up,
          wickDownColor: palette.down,
          borderVisible: false,
          title: symbol,
        })
      : chart.addSeries(LineSeries, {
          color: palette.primary,
          lineWidth: 2,
          title: `${symbol} (sim)`,
        });
    series.set('main', main);

    if (historical) {
      const volume = chart.addSeries(HistogramSeries, {
        color: palette.volume,
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
        lastValueVisible: false,
        priceLineVisible: false,
      });
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      series.set('volume', volume);
    }

    if (active.has('sma20')) series.set('sma20', chart.addSeries(LineSeries, lineOptions(palette, LOOK.sma20)));
    if (active.has('sma50')) series.set('sma50', chart.addSeries(LineSeries, lineOptions(palette, LOOK.sma50)));
    if (active.has('ema20')) series.set('ema20', chart.addSeries(LineSeries, lineOptions(palette, LOOK.ema20)));
    if (active.has('bollinger')) {
      series.set('bbUpper', chart.addSeries(LineSeries, lineOptions(palette, LOOK.bbBand)));
      series.set('bbMid', chart.addSeries(LineSeries, lineOptions(palette, LOOK.bbMid)));
      series.set('bbLower', chart.addSeries(LineSeries, lineOptions(palette, LOOK.bbBand)));
    }
    if (historical && active.has('vwap')) {
      series.set('vwap', chart.addSeries(LineSeries, lineOptions(palette, LOOK.vwap)));
    }

    // Oscillators get panes of their own under the price, on the same time
    // axis -- one chart, so the crosshair and zoom stay in lockstep.
    let pane = 0;
    if (showRsi) {
      pane += 1;
      const rsiSeries = chart.addSeries(
        LineSeries,
        { ...lineOptions(palette, LOOK.rsi), title: `RSI${RSI_PERIOD}`, lastValueVisible: true },
        pane,
      );
      rsiSeries.createPriceLine({ price: 70, color: palette.downSoft, lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true, title: '' });
      rsiSeries.createPriceLine({ price: 30, color: palette.upSoft, lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true, title: '' });
      series.set('rsi', rsiSeries);
    }
    if (showMacd) {
      pane += 1;
      series.set(
        'macdHist',
        chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane),
      );
      series.set('macd', chart.addSeries(LineSeries, lineOptions(palette, LOOK.macd), pane));
      series.set('macdSignal', chart.addSeries(LineSeries, lineOptions(palette, LOOK.macdSignal), pane));
    }
    // Keep the price pane dominant: oscillators are context, not the subject.
    // Stretch factors rather than pixel heights, so the split holds in a
    // quarter-screen cell as well as a full-screen one.
    const panes = chart.panes?.() ?? [];
    panes[0]?.setStretchFactor?.(4);
    for (let i = 1; i < panes.length; i += 1) panes[i]?.setStretchFactor?.(1);

    markersRef.current = historical ? createSeriesMarkers(main, []) : null;

    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (param.time === undefined) {
        setHoverIndex(null);
        return;
      }
      setHoverIndex(indexRef.current.get(String(param.time)) ?? null);
    });

    chartRef.current = chart;
    seriesRef.current = series;
    fittedRef.current = null;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = new Map();
      markersRef.current = null;
      setHoverIndex(null);
    };
    // Rebuilt on structure or theme; data flows through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structure, theme, hasData]);

  useEffect(() => {
    const series = seriesRef.current;
    const main = series.get('main');
    if (!main) return;
    const palette = readPalette(containerRef.current);

    if (historical) {
      main.setData(
        bars.map((bar) => ({
          time: bar.date as Time,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        })),
      );
      series.get('volume')?.setData(
        bars.map((bar) => ({ time: bar.date as Time, value: bar.volume, color: palette.volume })),
      );
    } else {
      main.setData(sim.map((point) => ({ time: point.time as UTCTimestamp, value: point.value })));
    }

    series.get('sma20')?.setData(toLine(times, studies.sma20));
    series.get('sma50')?.setData(toLine(times, studies.sma50));
    series.get('ema20')?.setData(toLine(times, studies.ema20));
    if (studies.bollinger) {
      series.get('bbUpper')?.setData(toLine(times, studies.bollinger.map((b) => b.upper)));
      series.get('bbMid')?.setData(toLine(times, studies.bollinger.map((b) => b.mid)));
      series.get('bbLower')?.setData(toLine(times, studies.bollinger.map((b) => b.lower)));
    }
    series.get('vwap')?.setData(toLine(times, studies.vwap));
    series.get('rsi')?.setData(toLine(times, studies.rsi));
    if (studies.macd) {
      series.get('macd')?.setData(toLine(times, studies.macd.line));
      series.get('macdSignal')?.setData(toLine(times, studies.macd.signal));
      const histogram: { time: Time; value: number; color: string }[] = [];
      studies.macd.histogram.forEach((value, index) => {
        if (value !== null && times[index] !== undefined) {
          histogram.push({ time: times[index], value, color: value >= 0 ? palette.upSoft : palette.downSoft });
        }
      });
      series.get('macdHist')?.setData(histogram);
    }

    const markers = markersRef.current;
    if (markers) {
      const onChart = new Set(bars.map((bar) => bar.date));
      const list: SeriesMarker<Time>[] = [];
      if (active.has('signals')) {
        const firstDate = bars[0]?.date ?? '';
        for (const signal of signals) {
          // Outside the window: dropped, not piled onto the first bar.
          if (signal.date < firstDate) continue;
          // A weekly or monthly bar is dated by its last session, so a signal
          // mid-bucket is moved onto the bar that contains it.
          const date = onChart.has(signal.date)
            ? signal.date
            : bars.find((bar) => bar.date >= signal.date)?.date;
          if (!date) continue;
          const bullish = signal.direction === 'bullish';
          list.push({
            time: date as Time,
            position: bullish ? 'belowBar' : 'aboveBar',
            shape: bullish ? 'arrowUp' : 'arrowDown',
            color: bullish ? palette.up : palette.down,
            // Arrows only: rule names on every marker piled into an unreadable
            // band. The readout names the rules for the bar under the cursor.
            text: '',
            id: signal.label,
          });
        }
      }
      list.sort((a, b) => String(a.time).localeCompare(String(b.time)));
      markers.setMarkers(list);
    }

    // Fit once per view; a ticking simulation must not snap the user's zoom back.
    if (fittedRef.current !== fitKey) {
      chartRef.current?.timeScale().fitContent();
      fittedRef.current = fitKey;
    }
  }, [historical, bars, sim, studies, times, signals, active, fitKey, theme, structure]);

  const index = hoverIndex ?? length - 1;
  const hovering = hoverIndex !== null;

  // Signals falling inside the readout's bar (a weekly bar holds five sessions).
  const barSignals = useMemo(() => {
    if (!historical || !active.has('signals') || index < 0) return [];
    const end = bars[index]?.date;
    const start = index > 0 ? bars[index - 1]?.date : '';
    if (!end) return [];
    return signals.filter((s) => s.date <= end && s.date > (start ?? ''));
  }, [historical, active, bars, index, signals]);

  if (!hasData) {
    return (
      <p className="rounded-sm border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
        No data in this window.
      </p>
    );
  }

  const bar = historical ? bars[index] : undefined;
  const prior = historical ? bars[index - 1] : undefined;
  const point = !historical ? sim[index] : undefined;
  const change =
    bar && prior ? bar.close / prior.close - 1 : point && sim[0] ? point.value / sim[0].value - 1 : null;

  const legend: { key: string; label: string; look: LineLook; value: string }[] = [];
  if (active.has('sma20')) legend.push({ key: 'sma20', label: 'SMA 20', look: LOOK.sma20, value: fmt(studies.sma20?.[index]) });
  if (active.has('sma50')) legend.push({ key: 'sma50', label: 'SMA 50', look: LOOK.sma50, value: fmt(studies.sma50?.[index]) });
  if (active.has('ema20')) legend.push({ key: 'ema20', label: 'EMA 20', look: LOOK.ema20, value: fmt(studies.ema20?.[index]) });
  if (active.has('bollinger')) {
    const band = studies.bollinger?.[index];
    legend.push({ key: 'bb', label: 'BB', look: LOOK.bbBand, value: `${fmt(band?.lower)} – ${fmt(band?.upper)}` });
  }
  if (historical && active.has('vwap')) legend.push({ key: 'vwap', label: 'VWAP', look: LOOK.vwap, value: fmt(studies.vwap?.[index]) });
  if (showRsi) legend.push({ key: 'rsi', label: `RSI ${RSI_PERIOD}`, look: LOOK.rsi, value: fmt(studies.rsi?.[index], 1) });
  if (showMacd) {
    legend.push({
      key: 'macd',
      label: 'MACD / sig',
      look: LOOK.macd,
      value: `${fmt(studies.macd?.line[index])} / ${fmt(studies.macd?.signal[index])}`,
    });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* A strip above the plot rather than a box over it: in a 2x2 grid an
          overlay covered a third of each chart. Always on, not only on hover: the date, T-offset and bar size are
          what make a chart readable, and hiding them until the pointer moves
          was half of what made the old one confusing. */}
      <div
        data-testid="chart-readout"
        className="shrink-0 border-b border-border px-3 py-1.5 font-mono text-[11px] tabular-nums text-card-foreground"
      >
        <div className="flex flex-wrap items-center gap-x-2 text-muted-foreground">
          {bar ? (
            <>
              <span data-testid="readout-date" className="text-foreground">
                {weekday(bar.date)} {bar.date}
              </span>
              <span data-testid="readout-offset" title="Bars before the latest bar in this window">
                {tOffset(index, length)}
              </span>
              <span>{INTERVAL_NOUN[interval]} bar</span>
            </>
          ) : point ? (
            <>
              <span data-testid="readout-date" className="text-foreground">
                {clockTime(point.time)} UTC
              </span>
              <span>1 s tick · simulated</span>
            </>
          ) : null}
          {hovering ? null : <span className="uppercase tracking-[0.12em]">latest</span>}
        </div>
        {bar ? (
          <div className="mt-0.5 flex flex-wrap gap-x-2">
            <span>O {fmt(bar.open)}</span>
            <span>H {fmt(bar.high)}</span>
            <span>L {fmt(bar.low)}</span>
            <span>C {fmt(bar.close)}</span>
            <span className={change !== null && change < 0 ? 'text-destructive' : 'text-primary'}>
              {change === null ? '' : `${change >= 0 ? '+' : ''}${(change * 100).toFixed(2)}%`}
            </span>
            <span className="text-muted-foreground">Vol {bar.volume.toLocaleString()}</span>
          </div>
        ) : point ? (
          <div className="mt-0.5 flex flex-wrap gap-x-2">
            <span>Px {fmt(point.value)}</span>
            <span className={change !== null && change < 0 ? 'text-destructive' : 'text-primary'}>
              {change === null ? '' : `${change >= 0 ? '+' : ''}${(change * 100).toFixed(2)}% vs seed`}
            </span>
          </div>
        ) : null}
        {legend.length > 0 ? (
          <ul data-testid="chart-legend" className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
            {legend.map((entry) => (
              <li key={entry.key} className="flex items-center gap-1.5">
                <Swatch look={entry.look} />
                <span className="text-muted-foreground">{entry.label}</span>
                <span>{entry.value}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {barSignals.length > 0 ? (
          <ul data-testid="readout-signals" className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
            {barSignals.slice(0, 4).map((signal, i) => (
              <li
                key={`${signal.date}-${signal.label}-${i}`}
                className={signal.direction === 'bullish' ? 'text-primary' : 'text-destructive'}
              >
                {signal.direction === 'bullish' ? '▲' : '▼'} {signal.label} · {signal.date}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <div
        ref={containerRef}
        data-testid="market-chart"
        data-mode={mode}
        className="min-h-[200px] w-full flex-1 overflow-hidden"
      />
      {historical && active.has('signals') ? (
        <span data-testid="chart-signal-count" className="sr-only">
          {signals.length} model signals for {symbol}
        </span>
      ) : null}
    </div>
  );
}
