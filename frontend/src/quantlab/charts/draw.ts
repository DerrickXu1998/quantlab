import { token } from '../../lib/token';
import type { CanvasSize } from './useCanvas2d';

// Re-exported so the charts keep a single import site for drawing helpers.
export { token };

export interface Series {
  /** Null is "no value yet" (an indicator still warming up): a gap, not a zero. */
  points: { date: string; value: number | null }[];
  color: string;
  /** Dashed lines read as "reference", which is what a benchmark is. */
  dashed?: boolean;
  fill?: string;
  /**
   * Step interpolation: the value holds flat until the next dated point, then
   * jumps. The honest shape for filing-stamped (point-in-time) data — a
   * diagonal would invent values between filings.
   */
  step?: boolean;
}

export interface Scale {
  x: (index: number) => number;
  y: (value: number) => number;
  min: number;
  max: number;
  length: number;
}

export const PADDING = { top: 10, right: 52, bottom: 20, left: 10 };

export function buildScale(seriesList: Series[], size: CanvasSize): Scale | null {
  const lengths = seriesList.map((s) => s.points.length);
  const length = Math.max(0, ...lengths);
  if (length < 2) return null;

  let min = Infinity;
  let max = -Infinity;
  for (const series of seriesList) {
    for (const point of series.points) {
      if (point.value === null) continue;
      if (point.value < min) min = point.value;
      if (point.value > max) max = point.value;
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  // A perfectly flat series would divide by zero; give it a visible band.
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.08;
  min -= pad;
  max += pad;

  const plotWidth = Math.max(1, size.width - PADDING.left - PADDING.right);
  const plotHeight = Math.max(1, size.height - PADDING.top - PADDING.bottom);

  return {
    length,
    min,
    max,
    x: (index) => PADDING.left + (index / (length - 1)) * plotWidth,
    y: (value) => PADDING.top + (1 - (value - min) / (max - min)) * plotHeight,
  };
}

export function drawGrid(
  ctx: CanvasRenderingContext2D,
  size: CanvasSize,
  scale: Scale,
  color: string,
  labelColor: string,
  formatValue: (value: number) => string,
  rows = 4,
): void {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.font = '10px "JetBrains Mono", ui-monospace, monospace';
  ctx.fillStyle = labelColor;
  ctx.textBaseline = 'middle';

  for (let row = 0; row <= rows; row += 1) {
    const value = scale.min + ((scale.max - scale.min) * row) / rows;
    // +0.5 keeps a 1px line on a pixel boundary rather than across two.
    const y = Math.round(scale.y(value)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(PADDING.left, y);
    ctx.lineTo(size.width - PADDING.right, y);
    ctx.stroke();
    ctx.fillText(formatValue(value), size.width - PADDING.right + 6, y);
  }
  ctx.restore();
}

export function drawSeries(ctx: CanvasRenderingContext2D, series: Series, scale: Scale): void {
  if (series.points.length < 2) return;

  const path = new Path2D();
  let started = false;
  let lastDrawn = -1;
  let lastY = 0;
  series.points.forEach((point, index) => {
    if (point.value === null) return;
    const x = scale.x(index);
    const y = scale.y(point.value);
    // A gap breaks the line rather than bridging it with an invented segment.
    if (!started || index !== lastDrawn + 1) {
      path.moveTo(x, y);
    } else if (series.step) {
      path.lineTo(x, lastY);
      path.lineTo(x, y);
    } else {
      path.lineTo(x, y);
    }
    started = true;
    lastDrawn = index;
    lastY = y;
  });

  if (series.fill) {
    const area = new Path2D();
    let firstX: number | null = null;
    let lastX: number | null = null;
    let fillLastY = 0;
    series.points.forEach((point, index) => {
      if (point.value === null) return;
      const x = scale.x(index);
      const y = scale.y(point.value);
      if (firstX === null) {
        area.moveTo(x, y);
        firstX = x;
      } else if (series.step) {
        area.lineTo(x, fillLastY);
        area.lineTo(x, y);
      } else {
        area.lineTo(x, y);
      }
      lastX = x;
      fillLastY = y;
    });
    if (firstX !== null && lastX !== null && lastX > firstX) {
      const baseline = scale.y(scale.min);
      area.lineTo(lastX, baseline);
      area.lineTo(firstX, baseline);
      area.closePath();
      ctx.fillStyle = series.fill;
      ctx.fill(area);
    }
  }

  ctx.save();
  ctx.strokeStyle = series.color;
  ctx.lineWidth = series.dashed ? 1 : 1.5;
  ctx.lineJoin = 'round';
  ctx.setLineDash(series.dashed ? [4, 4] : []);
  ctx.stroke(path);
  ctx.restore();
}

export function drawDateAxis(
  ctx: CanvasRenderingContext2D,
  size: CanvasSize,
  points: { date: string }[],
  color: string,
): void {
  if (points.length < 2) return;
  ctx.save();
  ctx.font = '10px "JetBrains Mono", ui-monospace, monospace';
  ctx.fillStyle = color;
  ctx.textBaseline = 'alphabetic';

  const first = points[0]?.date ?? '';
  const last = points[points.length - 1]?.date ?? '';
  const y = size.height - 6;
  ctx.textAlign = 'left';
  ctx.fillText(first, PADDING.left, y);
  ctx.textAlign = 'right';
  ctx.fillText(last, size.width - PADDING.right, y);
  ctx.restore();
}
