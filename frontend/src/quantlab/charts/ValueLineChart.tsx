import { useRef } from 'react';
import { formatNumeric, type NumericProps } from '../../components/ui/numeric';
import { buildScale, drawDateAxis, drawGrid, drawSeries, token, type Series } from './draw';
import { useCanvas2d } from './useCanvas2d';

export interface ValuePoint {
  date: string;
  value: number;
}

export interface ValueLineChartProps {
  points: ValuePoint[];
  /**
   * Step interpolation holds each value flat until the next dated point — the
   * honest shape for point-in-time series, where a diagonal would invent
   * values between filings.
   */
  step?: boolean;
  height?: number;
  format?: NumericProps['format'];
  testId?: string;
}

/**
 * A dated value series as a single line: macro history (yield, percent, index
 * points) and filing-stamped fundamentals. Not a price chart — no candles, no
 * volume — because the values behind it are not prices.
 */
export function ValueLineChart({
  points,
  step = false,
  height = 240,
  format = 'compact',
  testId = 'value-line-chart',
}: ValueLineChartProps) {
  const themeRef = useRef<HTMLDivElement | null>(null);

  const { wrapperRef, canvasRef, supported } = useCanvas2d(
    (ctx, size) => {
      const host = themeRef.current;
      const accent = token(host, '--primary');
      const muted = token(host, '--muted-foreground');
      const grid = token(host, '--grid');

      const series: Series = {
        points: points.map((point) => ({ date: point.date, value: point.value })),
        color: accent,
        fill: token(host, '--primary', 0.08),
        step,
      };

      const scale = buildScale([series], size);
      if (!scale) return;

      drawGrid(ctx, size, scale, grid, muted, (value) => formatNumeric(value, format));
      drawSeries(ctx, series, scale);
      drawDateAxis(ctx, size, points, muted);
    },
    [points, step, format],
  );

  const last = points[points.length - 1];

  return (
    <div ref={themeRef}>
      <div ref={wrapperRef} style={{ height }} className="relative w-full">
        {supported ? (
          <canvas ref={canvasRef} data-testid={testId} className="block h-full w-full" />
        ) : null}
        <p data-testid={`${testId}-summary`} className="sr-only">
          {points.length} points from {points[0]?.date ?? '—'} to {last?.date ?? '—'}, last value{' '}
          {last ? formatNumeric(last.value, format) : '—'}.
        </p>
        {!supported ? (
          <div className="flex h-full items-center justify-center font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            {last ? formatNumeric(last.value, format) : '—'}
          </div>
        ) : null}
      </div>
    </div>
  );
}
