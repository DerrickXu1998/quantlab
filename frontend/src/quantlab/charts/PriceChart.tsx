import { useRef } from 'react';
import { cn } from '../../lib/utils';
import { formatNumeric } from '../chrome/Numeric';
import type { BollingerBand } from '../data/indicators';
import { buildScale, drawDateAxis, drawGrid, drawSeries, token, type Series } from './draw';
import { useCanvas2d } from './useCanvas2d';

export interface PriceChartProps {
  /** Rolling intraday prices, oldest first. */
  series: number[];
  /** Null-padded overlays, aligned with `series`; omitted when toggled off. */
  bands?: BollingerBand[] | null;
  vwap?: (number | null)[] | null;
  height?: number;
  /**
   * Grow to fill the parent instead of taking a fixed pixel height.
   *
   * The same prop `EquityCurve` carries, and for the same reason: a terminal
   * fills its workspace. Pinned at 320px this chart left roughly 380px of dead
   * ground under the Market destination. The canvas already redraws from a
   * ResizeObserver, so growing costs nothing.
   */
  fill?: boolean;
}

/**
 * The rolling tick series with whatever overlays are switched on.
 *
 * Bollinger bands read as dashed reference lines and VWAP as a solid muted
 * one, leaving the accent for the price itself — the same colour grammar as
 * the equity curve, where the benchmark is the dashed line.
 */
export function PriceChart({
  series,
  bands = null,
  vwap = null,
  height = 320,
  fill = false,
}: PriceChartProps) {
  const themeRef = useRef<HTMLDivElement | null>(null);

  const { wrapperRef, canvasRef, supported } = useCanvas2d(
    (ctx, size) => {
      const host = themeRef.current;
      const accent = token(host, '--primary');
      const muted = token(host, '--muted-foreground');
      const tick = token(host, '--tick');
      const grid = token(host, '--grid');

      const toPoints = (values: (number | null)[]) =>
        values.map((value, index) => ({ date: String(index), value }));

      const pricePoints = toPoints(series);
      const seriesList: Series[] = [
        { points: pricePoints, color: accent, fill: token(host, '--primary', 0.08) },
      ];
      if (bands) {
        seriesList.push({
          points: bands.map((band, index) => ({ date: String(index), value: band.upper })),
          color: muted,
          dashed: true,
        });
        seriesList.push({
          points: bands.map((band, index) => ({ date: String(index), value: band.lower })),
          color: muted,
          dashed: true,
        });
      }
      if (vwap) seriesList.push({ points: toPoints(vwap), color: tick });

      const scale = buildScale(seriesList, size);
      if (!scale) return;

      drawGrid(ctx, size, scale, grid, muted, (value) => formatNumeric(value, 'price'));
      seriesList.slice(1).forEach((item) => drawSeries(ctx, item, scale));
      drawSeries(ctx, seriesList[0], scale);

      const axis = series.map((_, index) => ({
        date: index === series.length - 1 ? 'now' : `T-${series.length - 1 - index}`,
      }));
      drawDateAxis(ctx, size, axis, muted);
    },
    [series, bands, vwap],
  );

  const last = series[series.length - 1];

  return (
    <div ref={themeRef} className={cn(fill && 'flex min-h-0 flex-1 flex-col')}>
      <div
        ref={wrapperRef}
        style={fill ? undefined : { height }}
        // A floor, so a short viewport or several open sub-panels shrink the
        // chart rather than collapsing it to a hairline.
        className={cn('relative w-full', fill && 'min-h-[220px] flex-1')}
      >
        {supported ? <canvas ref={canvasRef} className="block h-full w-full" /> : null}
        <p data-testid="price-chart-summary" className="sr-only">
          {series.length} ticks, last at {formatNumeric(last ?? 0, 'price')}.
        </p>
        {!supported ? (
          <div className="flex h-full items-center justify-center font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            {formatNumeric(last ?? 0, 'price')}
          </div>
        ) : null}
      </div>
    </div>
  );
}
