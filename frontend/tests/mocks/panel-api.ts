/**
 * A controllable fake of the panel API that `usePanelSize` consumes.
 *
 * `PanelApiLike` in `src/components/usePanelSize.ts` is a structural shape
 * declared by this app, not a type borrowed from a docking library — panel
 * content has never been allowed to import one. This fake satisfies that shape
 * and nothing else.
 *
 * Why a fake at all: jsdom reports every box as 0x0, so a chart that sized
 * itself by observing its container would measure zero and silently render
 * nothing. Driving resize and visibility by hand is what lets a test assert
 * the chart reacts to them.
 *
 * It previously lived inside a `dockview-react` mock. The dock was retired
 * from the Research destination (docs/RESEARCH.md §1d), and the sizing seam
 * outlived it, so the fake moved here rather than being deleted with it.
 */

export interface FakeEmitter<T> {
  listeners: ((value: T) => void)[];
  fire(value: T): void;
}

function makeEmitter<T>(): FakeEmitter<T> & {
  event: (cb: (value: T) => void) => { dispose(): void };
} {
  const listeners: ((value: T) => void)[] = [];
  const emitter = {
    listeners,
    fire(value: T) {
      for (const listener of [...listeners]) listener(value);
    },
    event(cb: (value: T) => void) {
      listeners.push(cb);
      return {
        dispose() {
          const index = listeners.indexOf(cb);
          if (index >= 0) listeners.splice(index, 1);
        },
      };
    },
  };
  return emitter;
}

export interface FakePanelApi {
  width: number;
  height: number;
  isVisible: boolean;
  isActive: boolean;
  onDidDimensionsChange: (cb: (e: { width: number; height: number }) => void) => {
    dispose(): void;
  };
  onDidVisibilityChange: (cb: (e: { isVisible: boolean }) => void) => { dispose(): void };
  /** Test helpers — not part of the shape the app consumes. */
  _resize(width: number, height: number): void;
  _setVisible(isVisible: boolean): void;
}

export function createFakePanelApi(
  initial: { width?: number; height?: number; isVisible?: boolean } = {},
): FakePanelApi {
  const dimensions = makeEmitter<{ width: number; height: number }>();
  const visibility = makeEmitter<{ isVisible: boolean }>();

  const api: FakePanelApi = {
    width: initial.width ?? 800,
    height: initial.height ?? 400,
    isVisible: initial.isVisible ?? true,
    isActive: true,
    onDidDimensionsChange: dimensions.event,
    onDidVisibilityChange: visibility.event,
    _resize(width, height) {
      api.width = width;
      api.height = height;
      dimensions.fire({ width, height });
    },
    _setVisible(isVisible) {
      api.isVisible = isVisible;
      visibility.fire({ isVisible });
    },
  };
  return api;
}
