/**
 * jsdom has no ResizeObserver, and every box it does report is 0x0.
 *
 * This fake reports a fixed size once, synchronously, so components that size
 * a canvas from their wrapper get a plausible box instead of never drawing.
 * Written by hand rather than pulled from a polyfill for the same reason the
 * other mocks here are: the test needs a controllable size, not a faithful
 * implementation of the spec.
 */
export const OBSERVED_SIZE = { width: 640, height: 240 };

export class FakeResizeObserver implements ResizeObserver {
  private static instances: FakeResizeObserver[] = [];
  private callback: ResizeObserverCallback;
  private targets = new Set<Element>();

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    FakeResizeObserver.instances.push(this);
  }

  observe(target: Element): void {
    this.targets.add(target);
    this.emit();
  }

  unobserve(target: Element): void {
    this.targets.delete(target);
  }

  disconnect(): void {
    this.targets.clear();
  }

  private emit(): void {
    const entries = [...this.targets].map(
      (target) =>
        ({
          target,
          contentRect: { ...OBSERVED_SIZE, top: 0, left: 0, right: 640, bottom: 240, x: 0, y: 0 },
        }) as unknown as ResizeObserverEntry,
    );
    this.callback(entries, this);
  }

  /** Lets a test drive a resize without touching layout. */
  static resizeAll(width: number, height: number): void {
    Object.assign(OBSERVED_SIZE, { width, height });
    for (const instance of FakeResizeObserver.instances) instance.emit();
  }
}

export function installResizeObserver(): void {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;
}
