import { useEffect, useRef, useState } from 'react';

/**
 * Motion for the signed-out landing page only.
 *
 * The app itself allows one entrance and nothing that moves at rest. The
 * landing page keeps the second half of that rule: every movement here is
 * driven by the visitor's own scrolling, so a page left alone is still. Anyone
 * who has asked for reduced motion gets the same content, laid out statically.
 */

const REDUCED = '(prefers-reduced-motion: reduce)';

function matches(query: string): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(query).matches
    : false;
}

/** Tracks a media query. False where `matchMedia` does not exist (tests). */
export function useMediaQuery(query: string): boolean {
  const [value, setValue] = useState(() => matches(query));
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const list = window.matchMedia(query);
    const onChange = () => setValue(list.matches);
    onChange();
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query]);
  return value;
}

export function useReducedMotion(): boolean {
  return useMediaQuery(REDUCED);
}

/**
 * Calls `onFrame` once on mount and then at most once per animation frame
 * while the page scrolls or resizes. The callback writes styles straight to
 * DOM nodes: a React render per scroll frame would be far too slow.
 */
export function useScrollFrame(onFrame: () => void, enabled = true): void {
  const callback = useRef(onFrame);
  callback.current = onFrame;

  useEffect(() => {
    if (!enabled) return;
    let frame = 0;
    const run = () => {
      frame = 0;
      callback.current();
    };
    const schedule = () => {
      if (frame === 0) frame = window.requestAnimationFrame(run);
    };
    run();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    return () => {
      if (frame !== 0) window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
    };
  }, [enabled]);
}

export function clamp(value: number, low = 0, high = 1): number {
  return Math.min(high, Math.max(low, value));
}

/** Ease-out cubic: fast to start, settling gently, like a hand letting go. */
export function easeOut(t: number): number {
  return 1 - (1 - t) ** 3;
}

/**
 * How far the page has scrolled through a tall element, 0 to 1: 0 when its top
 * reaches the top of the viewport, 1 when its bottom reaches the bottom. This
 * is the travel of a `position: sticky` child pinned inside it.
 */
export function pinnedProgress(element: HTMLElement): number {
  const rect = element.getBoundingClientRect();
  const travel = rect.height - window.innerHeight;
  if (travel <= 0) return 0;
  return clamp(-rect.top / travel);
}

/**
 * True once the element has entered the viewport, and it stays true: content
 * reveals once and does not hide again when scrolled past. Starts true where
 * there is no IntersectionObserver (tests) or motion is reduced.
 */
export function useRevealed<T extends HTMLElement>(): [React.RefObject<T>, boolean] {
  const ref = useRef<T>(null);
  const reduced = useReducedMotion();
  const supported = typeof IntersectionObserver !== 'undefined';
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || !supported || reduced) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { rootMargin: '0px 0px -12% 0px', threshold: 0.1 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [supported, reduced]);

  return [ref, seen || !supported || reduced];
}
