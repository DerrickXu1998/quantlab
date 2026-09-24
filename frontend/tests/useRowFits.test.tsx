import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useRowFits } from '../src/chrome/useRowFits';

/**
 * jsdom lays nothing out, so the widths the hook reads are stubbed: each
 * child's natural width, and the window's.
 */
let viewport = 1000;
const CHILD_WIDTH = 600;

function stubLayout() {
  vi.spyOn(document.documentElement, 'clientWidth', 'get').mockImplementation(() => viewport);
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    return this.dataset.child ? CHILD_WIDTH : 0;
  });
}

function resizeTo(width: number) {
  viewport = width;
  act(() => {
    window.dispatchEvent(new Event('resize'));
  });
}

function Header({ enabled = true }: { enabled?: boolean }) {
  const { rowRef, fits } = useRowFits(enabled);
  return fits ? (
    <header ref={rowRef} data-testid="row">
      <div data-child="1" />
      <div data-child="1" />
    </header>
  ) : (
    <header data-testid="hamburger" />
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  viewport = 1000;
});

describe('useRowFits', () => {
  it('collapses a row that is wider than the window before it is shown', () => {
    stubLayout();
    viewport = 1000; // two 600px children need 1,200px

    render(<Header />);

    expect(screen.getByTestId('hamburger')).toBeInTheDocument();
  });

  it('keeps the row where it fits', () => {
    stubLayout();
    viewport = 1400;

    render(<Header />);

    expect(screen.getByTestId('row')).toBeInTheDocument();
  });

  it('collapses when the window is narrowed and comes back when it is widened', () => {
    stubLayout();
    viewport = 1400;
    render(<Header />);
    expect(screen.getByTestId('row')).toBeInTheDocument();

    resizeTo(1100);
    expect(screen.getByTestId('hamburger')).toBeInTheDocument();

    // Not yet: 1,150 is still short of the 1,200 the row measured.
    resizeTo(1150);
    expect(screen.getByTestId('hamburger')).toBeInTheDocument();

    resizeTo(1250);
    expect(screen.getByTestId('row')).toBeInTheDocument();
  });

  it('always collapses when disabled (below lg)', () => {
    stubLayout();
    viewport = 5000;

    render(<Header enabled={false} />);

    expect(screen.getByTestId('hamburger')).toBeInTheDocument();
  });
});
