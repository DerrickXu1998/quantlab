import { useRef } from 'react';
import { token } from './draw';
import { useCanvas2d } from './useCanvas2d';

/**
 * A bare trend line for a watchlist row: no axes, no grid, no labels. It says
 * "direction", and the number beside it says everything else.
 */
export function Sparkline({
  values,
  width = 56,
  height = 18,
  rising,
}: {
  values: number[];
  width?: number;
  height?: number;
  rising: boolean;
}) {
  const hostRef = useRef<HTMLSpanElement | null>(null);

  const { wrapperRef, canvasRef, supported } = useCanvas2d(
    (ctx, size) => {
      if (values.length < 2) return;
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;

      ctx.beginPath();
      values.forEach((value, index) => {
        const x = (index / (values.length - 1)) * size.width;
        const y = size.height - ((value - min) / span) * (size.height - 2) - 1;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = token(hostRef.current, rising ? '--primary' : '--destructive');
      ctx.lineWidth = 1;
      ctx.stroke();
    },
    [values, rising],
  );

  return (
    <span ref={hostRef} className="inline-block" aria-hidden="true">
      <span ref={wrapperRef} className="block" style={{ width, height }}>
        {supported ? <canvas ref={canvasRef} className="block" /> : null}
      </span>
    </span>
  );
}
