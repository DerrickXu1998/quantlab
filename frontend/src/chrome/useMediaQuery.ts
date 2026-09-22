import { useCallback, useSyncExternalStore } from 'react';

/**
 * Tailwind's `lg` breakpoint, in one place.
 *
 * The CSS and the JavaScript have to agree about where the phone layout ends.
 * Two copies of `1024px` drift, and the way they drift is silent: a component
 * renders its desktop branch while the stylesheet is still painting the mobile
 * one, and the result is a layout nobody wrote.
 */
export const LG_QUERY = '(min-width: 1024px)';

/**
 * Whether a media query currently matches.
 *
 * Almost everything responsive here is done in CSS, which is cheaper and does
 * not re-render. This exists for the one case CSS cannot express: when a thing
 * must appear in *different places* in the DOM at different widths, rendering
 * it in both and hiding one with `lg:hidden` leaves two copies in the
 * accessibility tree and two matches for every test query. The feed and
 * dataset disclosures are that case -- header on desktop, footer on a phone.
 *
 * `useSyncExternalStore` rather than an effect, so the first paint is already
 * correct instead of flipping after mount.
 *
 * `matchMedia` is missing in jsdom unless a test provides it. Treating that as
 * "desktop" keeps the existing suite describing the layout it was written
 * against, and keeps a missing browser API from being a blank screen.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window === 'undefined' || !window.matchMedia) return () => {};
      const list = window.matchMedia(query);
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    },
    [query],
  );

  const read = useCallback(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return true;
    return window.matchMedia(query).matches;
  }, [query]);

  return useSyncExternalStore(subscribe, read, () => true);
}

/** True on the widths the desktop terminal layout was designed for. */
export function useIsDesktop(): boolean {
  return useMediaQuery(LG_QUERY);
}
