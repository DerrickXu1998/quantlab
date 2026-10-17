import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  getUserSettings,
  updateUserSettings,
  type UserSettings,
  type UserSettingsDocument,
  type UserSettingsPatch,
} from '../api/client';
import { useTheme } from '../theme/ThemeProvider';

export type SettingsLoad =
  | { status: 'loading' }
  | { status: 'ready'; document: UserSettingsDocument }
  | { status: 'error'; message: string };

interface SettingsContextValue {
  load: SettingsLoad;
  /** Change some settings; resolves to an error message, or null when saved. */
  update: (patch: UserSettingsPatch) => Promise<string | null>;
  /** Take a document another endpoint answered with (the IBKR credential calls). */
  replace: (document: UserSettingsDocument) => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

/** RFC 7386, as the server applies it: objects merge, null resets, the rest replaces. */
export function mergePatch<T>(target: T, patch: unknown): T {
  if (patch === null || typeof patch !== 'object' || Array.isArray(patch)) return patch as T;
  const out: Record<string, unknown> = { ...((target as Record<string, unknown>) ?? {}) };
  for (const [key, value] of Object.entries(patch as Record<string, unknown>)) {
    if (value === null) delete out[key];
    else out[key] = mergePatch(out[key], value);
  }
  return out as T;
}

/**
 * The user's settings, held once for the whole app (inside the auth gate, so
 * they are read for the signed-in user only).
 *
 * Settings used to live in one browser -- the theme and the Market tab's saved
 * lists in localStorage. They are the account's now, so they follow the user
 * to another machine; this provider also carries the theme across: the
 * server's choice is applied on load, and the header's toggle is saved back.
 */
export function SettingsProvider({ children }: { children: ReactNode }) {
  const [load, setLoad] = useState<SettingsLoad>({ status: 'loading' });
  const { theme, setTheme } = useTheme();
  // The theme last agreed with the server, so a server-applied theme is not
  // saved straight back as if the user had toggled it.
  const syncedTheme = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getUserSettings()
      .then((document) => {
        if (cancelled) return;
        setLoad({ status: 'ready', document });
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoad({
            status: 'error',
            message: caught instanceof Error ? caught.message : 'settings unavailable',
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const update = useCallback(async (patch: UserSettingsPatch): Promise<string | null> => {
    let before: UserSettingsDocument | null = null;
    setLoad((current) => {
      if (current.status !== 'ready') return current;
      before = current.document;
      // Optimistic: the page reflects the change at once.
      return {
        status: 'ready',
        document: {
          ...current.document,
          settings: mergePatch<UserSettings>(current.document.settings, patch),
        },
      };
    });
    try {
      const document = await updateUserSettings(patch);
      setLoad({ status: 'ready', document });
      return null;
    } catch (caught) {
      const saved = before;
      if (saved) setLoad({ status: 'ready', document: saved });
      return caught instanceof Error ? caught.message : 'could not save settings';
    }
  }, []);

  const replace = useCallback((document: UserSettingsDocument) => {
    setLoad({ status: 'ready', document });
  }, []);

  // Theme: the account's choice wins on load. A user who has never saved
  // settings keeps the theme this browser already had, and it is saved for them.
  const serverTheme = load.status === 'ready' ? load.document.settings.appearance.theme : null;
  const neverSaved = load.status === 'ready' && load.document.updated_at === null;
  useEffect(() => {
    if (serverTheme === null) return;
    if (syncedTheme.current === null && neverSaved && theme !== serverTheme) {
      syncedTheme.current = theme;
      void update({ appearance: { theme } });
      return;
    }
    // The account's theme changed (first load, the settings dialog, or a
    // refused save rolling back): the page follows it.
    if (serverTheme !== syncedTheme.current) {
      syncedTheme.current = serverTheme;
      if (theme !== serverTheme) setTheme(serverTheme);
    }
    // `theme` is read, not followed: the effect below handles the toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverTheme, neverSaved, setTheme, update]);

  // The header's toggle changed the theme: save it to the account.
  useEffect(() => {
    if (syncedTheme.current === null || theme === syncedTheme.current) return;
    syncedTheme.current = theme;
    void update({ appearance: { theme } });
  }, [theme, update]);

  const value = useMemo(() => ({ load, update, replace }), [load, update, replace]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

/** The settings, or null outside a provider (a component rendered on its own). */
export function useSettings(): SettingsContextValue | null {
  return useContext(SettingsContext);
}
