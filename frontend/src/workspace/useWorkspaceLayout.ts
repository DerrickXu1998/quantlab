import { useEffect, useRef } from 'react';
import type { DockviewApi } from 'dockview-react';
import { buildDefaultLayout } from './defaultLayout';
import { clearLayout, loadLayout, saveLayout } from './layoutStorage';

/** Long enough that a divider drag settles into one write, short enough to feel immediate. */
const SAVE_DEBOUNCE_MS = 400;

/**
 * Applies the stored layout on ready and persists changes.
 *
 * Restore is guarded: a layout written by an older build can reference panels
 * that no longer exist, and a half-applied layout is worse than none. On any
 * failure the workspace is cleared, the unusable payload is discarded, and the
 * default is rebuilt via the same builder that backs reset (FR-007, FR-008).
 */
export function restoreOrBuildDefault(api: DockviewApi): void {
  const stored = loadLayout();

  if (stored) {
    try {
      api.fromJSON(stored.layout as Parameters<DockviewApi['fromJSON']>[0]);
      return;
    } catch {
      // Don't leave a payload behind that will fail again on the next load.
      clearLayout();
      api.clear();
    }
  }

  buildDefaultLayout(api);
}

export function useLayoutPersistence(api: DockviewApi | null): void {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!api) return;

    // onDidLayoutChange fires continuously while a divider is dragged, so the
    // write is debounced rather than issued per event.
    const subscription = api.onDidLayoutChange(() => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        saveLayout(api.toJSON());
      }, SAVE_DEBOUNCE_MS);
    });

    return () => {
      subscription.dispose();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [api]);
}
