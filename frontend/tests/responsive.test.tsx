import { act, render, renderHook, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LG_QUERY, useIsDesktop, useMediaQuery } from '../src/chrome/useMediaQuery';
import { Button } from '../src/components/ui/button';
import { fieldClasses } from '../src/components/ui/field';

/**
 * A controllable `matchMedia`, which jsdom does not implement.
 *
 * Returning a real listener set rather than a stub matters: the shell decides
 * where the disclosures render from this, and a query that never fires change
 * events would pass a test that a rotating phone fails.
 */
function installMatchMedia(matches: boolean) {
  const listeners = new Set<() => void>();
  const state = { matches };
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      media: query,
      get matches() {
        return state.matches;
      },
      addEventListener: (_: string, cb: () => void) => listeners.add(cb),
      removeEventListener: (_: string, cb: () => void) => listeners.delete(cb),
      addListener: (cb: () => void) => listeners.add(cb),
      removeListener: (cb: () => void) => listeners.delete(cb),
      dispatchEvent: () => false,
    })),
  );
  return {
    set(next: boolean) {
      state.matches = next;
      for (const cb of [...listeners]) cb();
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useMediaQuery', () => {
  it('reads the query on the first render, not after an effect', () => {
    installMatchMedia(false);

    const { result } = renderHook(() => useMediaQuery(LG_QUERY));

    // No `waitFor`: a value that only settles after mount is a visible flash
    // of the wrong layout.
    expect(result.current).toBe(false);
  });

  it('follows the viewport when it changes', () => {
    const media = installMatchMedia(false);
    const { result } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(false);

    act(() => media.set(true));

    expect(result.current).toBe(true);
  });

  /**
   * jsdom has no `matchMedia` unless a test installs one. Answering "desktop"
   * there keeps the rest of the suite describing the layout it was written
   * against, and keeps a missing browser API from rendering a blank shell.
   */
  it('answers desktop when matchMedia is unavailable', () => {
    vi.stubGlobal('matchMedia', undefined);

    const { result } = renderHook(() => useIsDesktop());

    expect(result.current).toBe(true);
  });
});

/**
 * The reported problem was a phone: at 390px the shell's header measured
 * 1,190px of content and every destination inherited a sideways scroll. These
 * assert the two rules that fixed it, at the level they are actually set --
 * one shared class string each, rather than per screen.
 */
describe('touch targets', () => {
  it('gives every button size a 44px target on touch and the dense row at lg', () => {
    for (const size of ['default', 'sm', 'icon'] as const) {
      render(
        <Button size={size} data-testid={`b-${size}`}>
          go
        </Button>,
      );
      const cls = screen.getByTestId(`b-${size}`).className;
      expect(cls, `${size} is not 44px on touch`).toMatch(/\bh-11\b/);
      expect(cls, `${size} does not restore the desktop height`).toMatch(/\blg:h-(8|7)\b/);
    }
  });

  it('gives every form control a 44px target, and 16px text so iOS does not zoom', () => {
    expect(fieldClasses).toMatch(/\bh-11\b/);
    expect(fieldClasses).toMatch(/\blg:h-9\b/);
    // Under 16px, focusing an input makes iOS Safari zoom the page, and the
    // zoom leaves the layout scrolled sideways with no way back.
    expect(fieldClasses).toMatch(/\btext-base\b/);
    expect(fieldClasses).toContain('lg:text-xs');
  });
});
