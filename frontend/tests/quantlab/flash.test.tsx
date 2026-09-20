import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FlashNumber } from '../../src/quantlab/chrome/FlashNumber';

/**
 * The tick flash is the surface's only continuous animation, and the one place
 * where two design rules meet: numbers flash the accent, and #FF4D4D is
 * reserved strictly for losses.
 */
describe('FlashNumber', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function flashClasses() {
    return screen.getByTestId('host').firstElementChild?.className ?? '';
  }

  it('does not flash on first render — arriving is not changing', () => {
    render(
      <div data-testid="host">
        <FlashNumber value={101.5} />
      </div>,
    );
    expect(flashClasses()).not.toMatch(/bg-primary/);
  });

  it('flashes the accent when a neutral value moves, and settles after 400ms', () => {
    const { rerender } = render(
      <div data-testid="host">
        <FlashNumber value={101.5} />
      </div>,
    );
    act(() => {
      rerender(
        <div data-testid="host">
          <FlashNumber value={102.25} />
        </div>,
      );
    });
    expect(flashClasses()).toMatch(/bg-primary/);

    act(() => void vi.advanceTimersByTime(399));
    expect(flashClasses()).toMatch(/bg-primary/);

    act(() => void vi.advanceTimersByTime(2));
    expect(flashClasses()).not.toMatch(/bg-primary/);
  });

  it('flashes a losing P&L red, never the accent', () => {
    // Flashing a loss acid lime would say "up" about a number that is down,
    // for 400ms, on a trading surface. It is the one flash that must not
    // happen.
    const { rerender } = render(
      <div data-testid="host">
        <FlashNumber value={-120} tone="signed" />
      </div>,
    );
    act(() => {
      rerender(
        <div data-testid="host">
          <FlashNumber value={-340} tone="signed" />
        </div>,
      );
    });
    expect(flashClasses()).toMatch(/bg-destructive/);
    expect(flashClasses()).not.toMatch(/bg-primary/);
  });

  it('flashes a gaining P&L the accent', () => {
    const { rerender } = render(
      <div data-testid="host">
        <FlashNumber value={120} tone="signed" />
      </div>,
    );
    act(() => {
      rerender(
        <div data-testid="host">
          <FlashNumber value={340} tone="signed" />
        </div>,
      );
    });
    expect(flashClasses()).toMatch(/bg-primary/);
    expect(flashClasses()).not.toMatch(/bg-destructive/);
  });
});
