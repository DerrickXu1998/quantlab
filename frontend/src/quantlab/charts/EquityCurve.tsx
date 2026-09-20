import { useRef } from 'react';
import type { EquityPoint } from '../../api/client';
import { formatNumeric } from '../chrome/Numeric';
import { buildScale, drawDateAxis, drawGrid, drawSeries, token, type Series } from './draw';
import { useCanvas2d } from './useCanvas2d';

export interface EquityCurveProps {
  equity: EquityPoint[];
  benchmark?: EquityPoint[];
  height?: number;
  /** Labels the two lines for anyone who cannot see the colours. */
  strategyLabel?: string;
  benchmarkLabel?: string;
}

/**
 * Strategy equity against its benchmark, hand-rendered.
 *
 * Custom rather than charted by a library: the surface needs a hairline grid,
 * mono axis labels and a dashed reference line to match everything around it,
 * and reskinning a library's defaults that far costs more than drawing two
 * polylines.
 */
export function EquityCurve({
  equity,
  benchmark = [],
  height = 240,
  strategyLabel = 'Strategy',
  benchmarkLabel = 'Benchmark',
}: EquityCurveProps) {
  const themeRef = useRef<HTMLDivElement | null>(null);

  const { wrapperRef, canvasRef, supported } = useCanvas2d(
    (ctx, size) => {
      const host = themeRef.current;
      const accent = token(host, '--primary');
      const muted = token(host, '--muted-foreground');
      const grid = token(host, '--grid');

      const seriesList: Series[] = [
        { points: equity, color: accent, fill: token(host, '--primary', 0.08) },
      ];
      if (benchmark.length > 1) {
        seriesList.push({ points: benchmark, color: muted, dashed: true });
      }

      const scale = buildScale(seriesList, size);
      if (!scale) return;

      drawGrid(ctx, size, scale, grid, muted, (value) => formatNumeric(value, 'currency'));
      // Benchmark first, so the strategy line sits on top of it.
      seriesList.slice(1).forEach((series) => drawSeries(ctx, series, scale));
      drawSeries(ctx, seriesList[0], scale);
      drawDateAxis(ctx, size, equity, muted);
    },
    [equity, benchmark],
  );

  const last = equity[equity.length - 1]?.value;
  const first = equity[0]?.value;

  return (
    <div ref={themeRef} className="flex flex-col gap-2">
      <div className="flex items-center gap-4 font-mono text-[10px] uppercase tracking-[0.12em]">
        <span className="flex items-center gap-1.5 text-primary">
          <span aria-hidden="true" className="h-px w-3 bg-primary" />
          {strategyLabel}
        </span>
        {benchmark.length > 1 ? (
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span aria-hidden="true" className="w-3 border-t border-dashed border-muted-foreground" />
            {benchmarkLabel}
          </span>
        ) : null}
      </div>

      <div ref={wrapperRef} style={{ height }} className="relative w-full">
        {supported ? (
          <canvas ref={canvasRef} className="block h-full w-full" />
        ) : null}
        {/* Readable without a canvas (and without sight): the same two numbers
            the curve is there to convey. */}
        <p data-testid="equity-curve-summary" className="sr-only">
          {strategyLabel} from {formatNumeric(first ?? 0, 'currency')} to{' '}
          {formatNumeric(last ?? 0, 'currency')} over {equity.length} sessions.
        </p>
        {!supported ? (
          <div className="flex h-full items-center justify-center font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            {formatNumeric(first ?? 0, 'currency')} → {formatNumeric(last ?? 0, 'currency')}
          </div>
        ) : null}
      </div>
    </div>
  );
}
