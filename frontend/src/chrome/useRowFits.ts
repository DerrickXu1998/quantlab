import { useEffect, useLayoutEffect, useRef, useState } from 'react';

/**
 * The width a flex row needs to lay every child out at its natural size:
 * padding, gaps, and each child's scrollWidth -- which, unlike its box, counts
 * content that has overflowed a child squeezed by `min-w-0`.
 */
function naturalWidth(row: HTMLElement): number {
  const style = getComputedStyle(row);
  const children = [...row.children] as HTMLElement[];
  const gap = parseFloat(style.columnGap) || 0;
  return (
    (parseFloat(style.paddingLeft) || 0) +
    (parseFloat(style.paddingRight) || 0) +
    gap * Math.max(0, children.length - 1) +
    children.reduce((sum, child) => sum + child.scrollWidth, 0)
  );
}

function viewportWidth(): number {
  return document.documentElement.clientWidth;
}

/**
 * Whether the header's full row fits the window, measured rather than guessed.
 *
 * A breakpoint cannot answer this. The row's width depends on who is signed in
 * (the email is in it), the browser's zoom and font size, and whatever the
 * feed status is saying, so any fixed number is too small for someone -- at
 * 1,024px the row drew Execution on top of the feed status. Instead the full
 * row is measured before it is painted and swapped for the hamburger if it
 * overflows; once collapsed, the window growing back to the last measured
 * width brings it back.
 *
 * `enabled` is false below `lg`, where the hamburger is used regardless: that
 * is touch territory, and the full row's controls are mouse-sized there.
 *
 * jsdom lays nothing out, so every width is 0 and the row always "fits" --
 * the suite keeps describing the desktop layout it was written against.
 */
export function useRowFits(enabled: boolean) {
  const row = useRef<HTMLElement>(null);
  const [fits, setFits] = useState(true);
  // The row's natural width the last time it was on screen.
  const needed = useRef(0);

  // Row on screen: measure before paint, and again whenever the window or the
  // row's contents change size (an email appearing on sign-in, say).
  useLayoutEffect(() => {
    if (!enabled || !fits) return;
    const element = row.current;
    if (!element) return;

    const check = () => {
      needed.current = naturalWidth(element);
      if (needed.current > viewportWidth() + 0.5) setFits(false);
    };
    check();

    window.addEventListener('resize', check);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(check);
    for (const child of element.children) observer?.observe(child);
    return () => {
      window.removeEventListener('resize', check);
      observer?.disconnect();
    };
  }, [enabled, fits]);

  // Collapsed: bring the row back once there is room for it. If its contents
  // have grown since, the effect above measures again and collapses it before
  // anything is painted.
  useEffect(() => {
    if (!enabled || fits) return;
    const onResize = () => {
      if (viewportWidth() >= needed.current) setFits(true);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [enabled, fits]);

  return { rowRef: row, fits: enabled && fits };
}
