import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

/**
 * Structural shape of the dock panel API this module needs.
 *
 * Deliberately declared here rather than imported from the docking library:
 * panel content components must not depend on dockview (see
 * contracts/ui-contracts.md), and the real panel api satisfies this shape.
 */
export interface PanelApiLike {
  width: number;
  height: number;
  isVisible: boolean;
  onDidDimensionsChange: (cb: (event: { width: number; height: number }) => void) => {
    dispose(): void;
  };
  onDidVisibilityChange: (cb: (event: { isVisible: boolean }) => void) => { dispose(): void };
}

export interface PanelSize {
  width: number;
  height: number;
  isVisible: boolean;
}

const DEFAULT_SIZE: PanelSize = { width: 0, height: 0, isVisible: true };

const PanelApiContext = createContext<PanelApiLike | null>(null);

export function PanelApiProvider({
  value,
  children,
}: {
  value: PanelApiLike | null;
  children: ReactNode;
}) {
  return createElement(PanelApiContext.Provider, { value }, children);
}

/**
 * Current size and visibility of the containing dock panel.
 *
 * Replaces observing the container with the panel's own events, because a panel
 * in an inactive tab has no meaningful box — the case where container
 * observation silently yields a zero-height chart (FR-009).
 *
 * Outside a dock panel it returns a default instead of throwing, so panel
 * content stays renderable standalone.
 */
export function usePanelSize(): PanelSize {
  const api = useContext(PanelApiContext);
  const [size, setSize] = useState<PanelSize>(() =>
    api ? { width: api.width, height: api.height, isVisible: api.isVisible } : DEFAULT_SIZE,
  );

  useEffect(() => {
    if (!api) {
      setSize(DEFAULT_SIZE);
      return;
    }

    setSize({ width: api.width, height: api.height, isVisible: api.isVisible });

    const dimensions = api.onDidDimensionsChange(({ width, height }) =>
      setSize((current) => ({ ...current, width, height })),
    );
    const visibility = api.onDidVisibilityChange(({ isVisible }) =>
      setSize((current) => ({ ...current, isVisible })),
    );

    return () => {
      dimensions.dispose();
      visibility.dispose();
    };
  }, [api]);

  return size;
}
