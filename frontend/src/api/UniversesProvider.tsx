import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { ApiError, createUniverse, listUniverses, type Universe } from './client';
import type { UniversePublishRequest } from './client';

export type UniversesStatus = 'loading' | 'ready' | 'unsupported' | 'error';

export interface UniversesState {
  universes: Universe[];
  status: UniversesStatus;
  message: string | null;
  reload: () => void;
}

export interface UniversesActions {
  publish: (body: UniversePublishRequest) => Promise<Universe>;
}

type ContextValue = UniversesState & UniversesActions;

const UniversesContext = createContext<ContextValue | null>(null);

function classify(caught: unknown): { status: 'unsupported' | 'error'; message: string } {
  if (caught instanceof ApiError && caught.status === 404) {
    return { status: 'unsupported', message: 'This backend does not serve universes.' };
  }
  return {
    status: 'error',
    message: caught instanceof ApiError ? caught.message : 'the universe list is unreachable',
  };
}

export function UniversesProvider({ children }: { children: React.ReactNode }) {
  const [universes, setUniverses] = useState<Universe[]>([]);
  const [status, setStatus] = useState<UniversesStatus>('loading');
  const [message, setMessage] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    listUniverses()
      .then((result) => {
        if (cancelled) return;
        setUniverses(result.items);
        setMessage(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const classified = classify(caught);
        setUniverses([]);
        setMessage(
          classified.status === 'unsupported'
            ? 'This backend does not publish universes.'
            : classified.message,
        );
        setStatus(classified.status);
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  const publish = useCallback(
    async (body: UniversePublishRequest) => {
      const created = await createUniverse(body);
      reload();
      return created;
    },
    [reload],
  );

  const value = useMemo(
    () => ({
      universes,
      status,
      message,
      reload,
      publish,
    }),
    [universes, status, message, reload, publish],
  );

  return <UniversesContext.Provider value={value}>{children}</UniversesContext.Provider>;
}

function useUniversesFetch(): UniversesState {
  const contextValue = useContext(UniversesContext);
  const [universes, setUniverses] = useState<Universe[]>([]);
  const [status, setStatus] = useState<UniversesStatus>('loading');
  const [message, setMessage] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (contextValue !== null) return;
    let cancelled = false;
    setStatus('loading');
    listUniverses()
      .then((result) => {
        if (cancelled) return;
        setUniverses(result.items);
        setMessage(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const classified = classify(caught);
        setUniverses([]);
        setMessage(
          classified.status === 'unsupported'
            ? 'This backend does not publish universes.'
            : classified.message,
        );
        setStatus(classified.status);
      });
    return () => {
      cancelled = true;
    };
  }, [nonce, contextValue]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return useMemo(
    () => ({ universes, status, message, reload }),
    [universes, status, message, reload],
  );
}

/**
 * The published universes and their read state.
 *
 * Shared across the app so a newly published universe appears in the screener
 * without a page reload. Falls back to a local fetch when there is no provider,
 * which keeps component tests simple.
 */
export function useUniverses(): UniversesState {
  const value = useContext(UniversesContext);
  const fallback = useUniversesFetch();

  return useMemo(() => {
    if (value === null) return fallback;
    const { universes, status, message, reload } = value;
    return { universes, status, message, reload };
  }, [value, fallback]);
}

/** The publish action, for screens that create new universes. */
export function usePublishUniverse(): UniversesActions['publish'] {
  const value = useContext(UniversesContext);
  if (value === null) {
    return () => Promise.reject(new Error('usePublishUniverse must be used inside a UniversesProvider'));
  }
  return value.publish;
}
