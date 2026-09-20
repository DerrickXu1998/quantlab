import { useEffect, useMemo, useState, type FunctionComponent } from 'react';
import { vi } from 'vitest';

/**
 * Hand-written fake of the `dockview-react` surface this app uses.
 * Registered globally in tests/setup.ts.
 *
 * Why: dockview lays out from real element dimensions, and jsdom reports every
 * box as 0x0, so a real DockviewReact renders no usable panel tree. This fake
 * renders each registered panel directly and hands it a controllable panel API,
 * so tests can drive resize/visibility transitions by hand.
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
  /** Test helpers — not part of the real dockview API. */
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

export interface FakeDockviewApi {
  toJSON: ReturnType<typeof vi.fn>;
  fromJSON: ReturnType<typeof vi.fn>;
  clear: ReturnType<typeof vi.fn>;
  addPanel: ReturnType<typeof vi.fn>;
  addFloatingGroup: ReturnType<typeof vi.fn>;
  removePanel: ReturnType<typeof vi.fn>;
  getPanel: ReturnType<typeof vi.fn>;
  onDidLayoutChange: (cb: () => void) => { dispose(): void };
  panels: { id: string; api: { setSize: ReturnType<typeof vi.fn> } }[];
  _fireLayoutChange(): void;
}

export const createdDockviewApis: FakeDockviewApi[] = [];

/** Set by a test to make the next fromJSON throw, exercising the FR-008 fallback. */
export const mockControls = { fromJSONThrows: false };

export function resetDockviewMock() {
  createdDockviewApis.length = 0;
  panelApis.clear();
  mockControls.fromJSONThrows = false;
}

function createFakeDockviewApi(): FakeDockviewApi {
  const layoutChange = makeEmitter<void>();
  // Starts empty, as real dockview does: panels exist only once added.
  const panels: { id: string; api: { setSize: ReturnType<typeof vi.fn> } }[] = [];

  const api: FakeDockviewApi = {
    toJSON: vi.fn(() => ({ grid: { root: {} }, panels: {} })),
    fromJSON: vi.fn(() => {
      if (mockControls.fromJSONThrows) throw new Error('mock: invalid layout');
    }),
    clear: vi.fn(),
    addPanel: vi.fn((options: { id: string }) => {
      // Real panels carry their own api; the layout builder uses setSize on it.
      const panel = { id: options.id, api: { setSize: vi.fn() } };
      panels.push(panel);
      return panel;
    }),
    addFloatingGroup: vi.fn(),
    removePanel: vi.fn((panel: { id: string }) => {
      const index = panels.findIndex((p) => p.id === panel.id);
      if (index >= 0) panels.splice(index, 1);
    }),
    getPanel: vi.fn((id: string) => panels.find((p) => p.id === id)),
    onDidLayoutChange: layoutChange.event,
    panels,
    _fireLayoutChange: () => layoutChange.fire(undefined as void),
  };
  return api;
}

export interface IDockviewPanelProps {
  api: FakePanelApi;
}

export interface IDockviewReactProps {
  components: Record<string, FunctionComponent<IDockviewPanelProps>>;
  onReady: (event: { api: FakeDockviewApi }) => void;
  theme?: unknown;
  className?: string;
}

/** Panel id → its fake panel API, so tests can drive resize/visibility per panel. */
export const panelApis = new Map<string, FakePanelApi>();

export function DockviewReact({ components, onReady, className }: IDockviewReactProps) {
  const panelIds = useMemo(() => Object.keys(components), [components]);
  const [api] = useState(() => {
    const created = createFakeDockviewApi();
    createdDockviewApis.push(created);
    return created;
  });

  // Panel APIs must be stable across renders, or subscriptions would be torn
  // down and rebuilt on every parent render.
  const [apis] = useState(() => {
    const map = new Map<string, FakePanelApi>();
    for (const id of panelIds) {
      const panelApi = createFakePanelApi();
      map.set(id, panelApi);
      panelApis.set(id, panelApi);
    }
    return map;
  });

  useEffect(() => {
    onReady({ api });
    // Fire once on mount, mirroring dockview's onReady contract.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div data-testid="dockview" className={className}>
      {panelIds.map((id) => {
        const Panel = components[id];
        return (
          <div key={id} data-testid={`panel-${id}`}>
            <Panel api={apis.get(id)!} />
          </div>
        );
      })}
    </div>
  );
}

export const themeLight = {
  name: 'light',
  className: 'dockview-theme-light',
  colorScheme: 'light',
};
export const themeDark = { name: 'dark', className: 'dockview-theme-dark', colorScheme: 'dark' };
