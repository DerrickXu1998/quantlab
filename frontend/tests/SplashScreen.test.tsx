import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildEdges, scatterPoints, seededRandom, selectConnected } from '../src/splash/particles';
import { SplashScreen } from '../src/splash/SplashScreen';
import { ThemeProvider } from '../src/theme/ThemeProvider';
import { mockSystemPrefersDark } from './mocks/match-media';

function renderSplash(onComplete = vi.fn()) {
  render(
    <ThemeProvider>
      <SplashScreen onComplete={onComplete} />
    </ThemeProvider>,
  );
  return onComplete;
}

describe('particle field geometry', () => {
  it('scatters the requested number of points across the viewport', () => {
    const points = scatterPoints(200, 800, 600, seededRandom(7));

    expect(points).toHaveLength(200);
    for (const point of points) {
      expect(point.x).toBeGreaterThanOrEqual(0);
      expect(point.x).toBeLessThanOrEqual(800);
      expect(point.y).toBeGreaterThanOrEqual(0);
      expect(point.y).toBeLessThanOrEqual(600);
    }
  });

  it('spreads points out rather than clumping them at the centre', () => {
    const points = scatterPoints(300, 800, 600, seededRandom(7));
    const hugging = points.filter((point) => Math.hypot(point.x - 400, point.y - 300) < 30);

    expect(hugging.length).toBeLessThan(points.length * 0.1);
  });

  it('leaves part of the field unconnected', () => {
    const connected = selectConnected(600, 0.6, seededRandom(11));

    // A meaningful mix both ways — neither a full web nor a bare scatter.
    expect(connected.length).toBeGreaterThan(600 * 0.4);
    expect(connected.length).toBeLessThan(600 * 0.8);
  });

  it('builds edges only between the connected subset', () => {
    const points = Array.from({ length: 40 }, (_, i) => ({ x: (i % 8) * 10, y: (i / 8) * 10 }));
    const connected = selectConnected(points.length, 0.5, seededRandom(3));
    const subset = connected.map((index) => points[index]);

    const edges = buildEdges(subset, 40, 2).map(({ a, b }) => ({
      a: connected[a],
      b: connected[b],
    }));

    const unconnected = new Set(points.map((_, i) => i));
    for (const index of connected) unconnected.delete(index);
    for (const edge of edges) {
      expect(unconnected.has(edge.a)).toBe(false);
      expect(unconnected.has(edge.b)).toBe(false);
    }
  });

  it('connects each point only to near neighbours', () => {
    const points = [
      { x: 0, y: 0 },
      { x: 5, y: 0 },
      { x: 10, y: 0 },
      { x: 900, y: 900 }, // far away: must stay unconnected
    ];
    const edges = buildEdges(points, 20, 2);

    expect(edges.length).toBeGreaterThan(0);
    expect(edges.some((edge) => edge.a === 3 || edge.b === 3)).toBe(false);
  });

  it('never emits an edge twice or an edge to itself', () => {
    const points = Array.from({ length: 12 }, (_, i) => ({ x: i * 4, y: (i % 3) * 4 }));
    const edges = buildEdges(points, 30, 3);

    const keys = edges.map(({ a, b }) => (a < b ? `${a}-${b}` : `${b}-${a}`));
    expect(new Set(keys).size).toBe(keys.length);
    expect(edges.every((edge) => edge.a !== edge.b)).toBe(true);
  });

  it('scatters deterministically so the boot sequence is identical each load', () => {
    expect(scatterPoints(20, 800, 600, seededRandom(42))).toEqual(
      scatterPoints(20, 800, 600, seededRandom(42)),
    );
  });
});

describe('SplashScreen', () => {
  beforeEach(() => {
    mockSystemPrefersDark(false);
  });

  it('announces itself as a loading state', () => {
    renderSplash();
    const splash = screen.getByTestId('splash-screen');
    expect(splash).toHaveAttribute('role', 'status');
    expect(splash).toHaveAccessibleName(/loading quantlab/i);
  });

  it('falls back gracefully when the canvas cannot animate', async () => {
    renderSplash();
    // jsdom has no 2D context, so the component must degrade rather than throw.
    expect(await screen.findByTestId('splash-static')).toBeInTheDocument();
  });

  it('enters the main page on its own, with no click needed', async () => {
    const onComplete = renderSplash();
    await waitFor(() => expect(onComplete).toHaveBeenCalled(), { timeout: 4500 });
  });

  it('can be skipped early by the impatient', async () => {
    const user = userEvent.setup();
    const onComplete = renderSplash();

    await user.click(screen.getByTestId('splash-skip'));

    await waitFor(() => expect(onComplete).toHaveBeenCalled());
  });

  it('enters only once however many times it is clicked', async () => {
    const user = userEvent.setup();
    const onComplete = renderSplash();

    const skip = screen.getByTestId('splash-skip');
    await user.click(skip);
    await user.click(skip);
    await user.click(screen.getByTestId('splash-screen'));

    await waitFor(() => expect(onComplete).toHaveBeenCalled());
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it('respects prefers-reduced-motion by skipping the animation', async () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    const onComplete = renderSplash();

    expect(screen.getByTestId('splash-static')).toBeInTheDocument();
    expect(screen.queryByTestId('splash-canvas')).not.toBeInTheDocument();
    await waitFor(() => expect(onComplete).toHaveBeenCalled(), { timeout: 2000 });
  });
});
