import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FlashNumber } from '../../src/quantlab/chrome/FlashNumber';
import { FeedProvider, useTick } from '../../src/quantlab/feed/FeedProvider';
import { seedTick, simulateTick } from '../../src/quantlab/feed/simulateTick';

function Readout({ symbol }: { symbol: string }) {
  const tick = useTick(symbol);
  return <span data-testid="price">{tick ? tick.price.toFixed(4) : 'none'}</span>;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('simulateTick', () => {
  it('is deterministic for a given source of randomness', () => {
    const fixed = () => 0.75;
    const first = simulateTick(seedTick('AAA', 100), fixed);
    const second = simulateTick(seedTick('AAA', 100), fixed);

    expect(first.price).toBe(second.price);
  });

  it('reports change against the seed, which is the real last close', () => {
    const next = simulateTick(seedTick('AAA', 100), () => 1);

    expect(next.changePct).toBeCloseTo(next.price / 100 - 1, 10);
  });

  it('never walks a price to zero or below', () => {
    let tick = seedTick('AAA', 0.02);
    for (let i = 0; i < 500; i += 1) tick = simulateTick(tick, () => 0);

    expect(tick.price).toBeGreaterThan(0);
  });

  it('keeps the sparkline history bounded', () => {
    let tick = seedTick('AAA', 100);
    for (let i = 0; i < 200; i += 1) tick = simulateTick(tick, () => 0.5);

    expect(tick.history.length).toBeLessThanOrEqual(24);
  });
});

describe('FeedProvider', () => {
  it('seeds from the supplied real close before any tick', () => {
    render(
      <FeedProvider seeds={{ AAA: 123.45 }} rng={() => 0.5}>
        <Readout symbol="AAA" />
      </FeedProvider>,
    );

    expect(screen.getByTestId('price')).toHaveTextContent('123.4500');
  });

  it('emits on the 800ms cadence and not before', () => {
    render(
      <FeedProvider seeds={{ AAA: 100 }} rng={() => 1}>
        <Readout symbol="AAA" />
      </FeedProvider>,
    );

    act(() => {
      vi.advanceTimersByTime(799);
    });
    expect(screen.getByTestId('price')).toHaveTextContent('100.0000');

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByTestId('price')).not.toHaveTextContent('100.0000');
  });

  it('stops ticking once unmounted', () => {
    const rng = vi.fn(() => 0.5);
    const { unmount } = render(
      <FeedProvider seeds={{ AAA: 100 }} rng={rng}>
        <Readout symbol="AAA" />
      </FeedProvider>,
    );

    unmount();
    rng.mockClear();
    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    expect(rng).not.toHaveBeenCalled();
  });

  it('reports nothing for a symbol it was never given', () => {
    render(
      <FeedProvider seeds={{ AAA: 100 }}>
        <Readout symbol="ZZZ" />
      </FeedProvider>,
    );

    expect(screen.getByTestId('price')).toHaveTextContent('none');
  });
});

describe('FlashNumber', () => {
  it('does not flash on first render — arriving is not changing', () => {
    render(<FlashNumber value={10} />);

    expect(document.querySelector('[data-flash="on"]')).toBeNull();
  });

  it('flashes on change and clears itself after 400ms', () => {
    const { rerender } = render(<FlashNumber value={10} />);

    rerender(<FlashNumber value={11} />);
    expect(document.querySelector('[data-flash="on"]')).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(399);
    });
    expect(document.querySelector('[data-flash="on"]')).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(document.querySelector('[data-flash="on"]')).toBeNull();
  });

  it('renders an absent value as a dash rather than zero', () => {
    render(<FlashNumber value={null} />);

    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
