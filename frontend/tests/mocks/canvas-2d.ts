import { vi } from 'vitest';

/**
 * A recording 2D context.
 *
 * jsdom throws "not implemented" for getContext, so chart components would
 * either crash or silently take their no-canvas fallback and prove nothing.
 * This records the calls instead, which is the only thing worth asserting:
 * that a curve with data actually strokes a path.
 */
export interface RecordedContext {
  strokes: number;
  fills: number;
  texts: string[];
  setTransform: ReturnType<typeof vi.fn>;
}

const recordings = new WeakMap<HTMLCanvasElement, RecordedContext>();

/** jsdom has no Path2D either, and draw.ts builds its lines through one. */
class FakePath2D {
  moveTo(): void {}
  lineTo(): void {}
  closePath(): void {}
}

export function installCanvas2d(): void {
  (globalThis as { Path2D?: unknown }).Path2D = FakePath2D;

  HTMLCanvasElement.prototype.getContext = function getContext(this: HTMLCanvasElement) {
    const record: RecordedContext = recordings.get(this) ?? {
      strokes: 0,
      fills: 0,
      texts: [],
      setTransform: vi.fn(),
    };
    recordings.set(this, record);

    const noop = () => {};
    return {
      canvas: this,
      setTransform: record.setTransform,
      clearRect: noop,
      save: noop,
      restore: noop,
      beginPath: noop,
      moveTo: noop,
      lineTo: noop,
      closePath: noop,
      setLineDash: noop,
      stroke: () => {
        record.strokes += 1;
      },
      fill: () => {
        record.fills += 1;
      },
      fillRect: noop,
      fillText: (text: string) => {
        record.texts.push(text);
      },
      measureText: () => ({ width: 0 }),
      lineWidth: 1,
      lineJoin: 'round',
      strokeStyle: '',
      fillStyle: '',
      font: '',
      textAlign: 'left',
      textBaseline: 'alphabetic',
    } as unknown as CanvasRenderingContext2D;
  } as HTMLCanvasElement['getContext'];
}

export function recordingFor(canvas: HTMLCanvasElement): RecordedContext | undefined {
  return recordings.get(canvas);
}
