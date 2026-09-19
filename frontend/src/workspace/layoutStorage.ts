export const LAYOUT_STORAGE_KEY = 'quantlab-workspace-layout';

/** Bump to deliberately discard layouts written by an incompatible build. */
export const LAYOUT_VERSION = 1;

export interface StoredLayout {
  version: number;
  layout: unknown;
}

/**
 * Neither load nor save may throw: a bad or unavailable layout must never be
 * what stops the workspace from rendering (FR-008).
 */
export function loadLayout(): StoredLayout | null {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
  } catch {
    return null; // storage unavailable (private mode, disabled)
  }
  if (!raw) return null;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return null;

    const record = parsed as Partial<StoredLayout>;
    if (record.version !== LAYOUT_VERSION) return null;
    if (record.layout === undefined || record.layout === null) return null;

    return { version: record.version, layout: record.layout };
  } catch {
    return null; // unparseable payload
  }
}

export function saveLayout(layout: unknown): void {
  try {
    const record: StoredLayout = { version: LAYOUT_VERSION, layout };
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(record));
  } catch {
    // A failed write must not break the session; the layout simply is not kept.
  }
}

export function clearLayout(): void {
  try {
    window.localStorage.removeItem(LAYOUT_STORAGE_KEY);
  } catch {
    // Nothing useful to do; treated as already cleared.
  }
}
