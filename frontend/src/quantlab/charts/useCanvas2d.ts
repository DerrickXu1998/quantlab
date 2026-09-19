import { useCallback, useEffect, useRef, useState } from 'react';

export interface CanvasSize {
  width: number;
  height: number;
}

export type DrawFn = (ctx: CanvasRenderingContext2D, size: CanvasSize) => void;

/**
 * A DPR-aware 2D canvas that redraws when its box or its data changes.
 *
 * Deliberately not built on `usePanelSize`: that hook reports the *dock panel's*
 * size and answers {0,0} outside one, so a chart on this surface would never
 * size at all. A ResizeObserver on the wrapper is the honest source here.
 *
 * The backing store is scaled by devicePixelRatio and the context transformed
 * to match, so `draw` works in CSS pixels and lines land on whole device pixels
 * instead of blurring across two.
 *
 * Returns `supported: false` when there is no 2D context (jsdom), so callers
 * can render a DOM fallback rather than a blank box.
 */
export function useCanvas2d(draw: DrawFn, deps: unknown[] = []) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const [size, setSize] = useState<CanvasSize>({ width: 0, height: 0 });
  const [supported, setSupported] = useState(true);

  // Held in a ref so a new inline `draw` closure on every render does not
  // invalidate the callback and force a redraw.
  const drawRef = useRef(draw);
  drawRef.current = draw;

  const { width, height } = size;

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || width <= 0 || height <= 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      setSupported(false);
      return;
    }

    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    drawRef.current(ctx, { width, height });
  }, [width, height]);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper || typeof ResizeObserver === 'undefined') return;

    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (!box) return;
      setSize((current) =>
        current.width === box.width && current.height === box.height
          ? current
          : { width: box.width, height: box.height },
      );
    });
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    // Coalesced: a resize drag would otherwise redraw once per observed frame.
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      render();
    });
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [render, ...deps]);

  return { wrapperRef, canvasRef, size, supported };
}
