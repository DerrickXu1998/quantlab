import { useRef } from 'react';
import { formatNumeric } from '../chrome/Numeric';
import type { MacdResult } from '../data/indicators';
import { PADDING, token } from './draw';
import { useCanvas2d } from './useCanvas2d';

/**
 * MACD (12, 26, 9) as a sub-panel: histogram bars around a zero line, the MACD
 * line in accent, the signal line dashed — the same "solid is the thing, dashed
 * is the reference" grammar as everywhere else on the surface.
 *
 * Negative bars are muted rather than red: a falling oscillator is not a loss,
 * and red is reserved for losses.
 */
export function MacdChart({ macd, height = 96 }: { macd: MacdResult; height?: number }) {
  const themeRef = useRef<HTMLDivElement | null>(null);

  const { wrapperRef, canvasRef, supported } = useCanvas2d(
    (ctx, size) => {
      const host = themeRef.current;
      const accent = token(host, '--primary');
      const accentFill = token(host, '--primary', 0.35);
      const muted = token(host, '--muted-foreground');
      const mutedFill = token(host, '--muted-foreground', 0.3);

      const all = [...macd.line, ...macd.signal, ...macd.histogram].filter(
        (value): value is number => value !== null,
      );
      if (all.length < 2) return;
      let min = Math.min(...all, 0);
      let max = Math.max(...all, 0);
      if (min === max) {
        min -= 1;
        max += 1;
      }
      const pad = (max - min) * 0.1;
      min -= pad;
      max += pad;

      const length = macd.line.length;
      const plotWidth = Math.max(1, size.width - PADDING.left - PADDING.right);
      const plotHeight = Math.max(1, size.height - PADDING.top - PADDING.bottom);
      const x = (index: number) => PADDING.left + (index / Math.max(1, length - 1)) * plotWidth;
      const y = (value: number) => PADDING.top + (1 - (value - min) / (max - min)) * plotHeight;

      ctx.save();
      ctx.font = '10px "JetBrains Mono", ui-monospace, monospace';
      ctx.fillStyle = muted;
      ctx.textBaseline = 'middle';
      ctx.fillText(formatNumeric(max - pad, 'price'), size.width - PADDING.right + 6, y(max - pad));
      ctx.fillText(formatNumeric(min + pad, 'price'), size.width - PADDING.right + 6, y(min + pad));

      const zeroY = Math.round(y(0)) + 0.5;
      ctx.strokeStyle = token(host, '--grid');
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(PADDING.left, zeroY);
      ctx.lineTo(size.width - PADDING.right, zeroY);
      ctx.stroke();

      const barWidth = Math.max(1, plotWidth / Math.max(1, length) - 1);
      macd.histogram.forEach((value, index) => {
        if (value === null) return;
        ctx.fillStyle = value >= 0 ? accentFill : mutedFill;
        const top = y(Math.max(value, 0));
        const bottom = y(Math.min(value, 0));
        ctx.fillRect(x(index) - barWidth / 2, top, barWidth, Math.max(1, bottom - top));
      });
      ctx.restore();

      const drawLine = (values: (number | null)[], color: string, dashed: boolean) => {
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = dashed ? 1 : 1.5;
        ctx.lineJoin = 'round';
        ctx.setLineDash(dashed ? [4, 4] : []);
        ctx.beginPath();
        let started = false;
        values.forEach((value, index) => {
          if (value === null) return;
          if (!started) ctx.moveTo(x(index), y(value));
          else ctx.lineTo(x(index), y(value));
          started = true;
        });
        ctx.stroke();
        ctx.restore();
      };
      drawLine(macd.signal, muted, true);
      drawLine(macd.line, accent, false);
    },
    [macd],
  );

  return (
    <div ref={themeRef}>
      <div ref={wrapperRef} style={{ height }} className="relative w-full">
        {supported ? <canvas ref={canvasRef} className="block h-full w-full" /> : null}
      </div>
    </div>
  );
}
