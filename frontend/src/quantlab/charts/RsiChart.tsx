import { useRef } from 'react';
import { PADDING, token } from './draw';
import { useCanvas2d } from './useCanvas2d';

/**
 * RSI (14) as a sub-panel under the price chart.
 *
 * The range is fixed at 0–100 with the 30/70 guides dashed in, so the line's
 * position reads without an axis — the live value sits in the panel header.
 */
export function RsiChart({ values, height = 88 }: { values: (number | null)[]; height?: number }) {
  const themeRef = useRef<HTMLDivElement | null>(null);

  const { wrapperRef, canvasRef, supported } = useCanvas2d(
    (ctx, size) => {
      const host = themeRef.current;
      const accent = token(host, '--primary');
      const muted = token(host, '--muted-foreground');

      const plotWidth = Math.max(1, size.width - PADDING.left - PADDING.right);
      const plotHeight = Math.max(1, size.height - PADDING.top - PADDING.bottom);
      const x = (index: number) =>
        PADDING.left + (index / Math.max(1, values.length - 1)) * plotWidth;
      const y = (value: number) => PADDING.top + (1 - value / 100) * plotHeight;

      ctx.save();
      ctx.strokeStyle = muted;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.font = '10px "JetBrains Mono", ui-monospace, monospace';
      ctx.fillStyle = muted;
      ctx.textBaseline = 'middle';
      for (const level of [30, 70]) {
        const levelY = Math.round(y(level)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(PADDING.left, levelY);
        ctx.lineTo(size.width - PADDING.right, levelY);
        ctx.stroke();
        ctx.fillText(String(level), size.width - PADDING.right + 6, levelY);
      }
      ctx.restore();

      ctx.save();
      ctx.strokeStyle = accent;
      ctx.lineWidth = 1.5;
      ctx.lineJoin = 'round';
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
    },
    [values],
  );

  return (
    <div ref={themeRef}>
      <div ref={wrapperRef} style={{ height }} className="relative w-full">
        {supported ? <canvas ref={canvasRef} className="block h-full w-full" /> : null}
      </div>
    </div>
  );
}
