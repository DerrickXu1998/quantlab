import { useCallback, useEffect, useState } from 'react';
import {
  createStrategy,
  deleteStrategy,
  listStrategies,
  replaceStrategy,
  ApiError,
} from '../api/client';
import type { Strategy, StrategySpec } from '../api/types';

export type LibraryStatus = 'loading' | 'ready' | 'error';

export interface StrategyLibrary {
  items: Strategy[];
  status: LibraryStatus;
  /** Set when the list could not be read; null once it has been. */
  error: string | null;
  reload: () => void;
  save: (spec: StrategySpec, id: string | null) => Promise<Strategy>;
  remove: (id: string) => Promise<void>;
}

/**
 * The caller's saved strategies, from `/api/v1/strategies`.
 *
 * Kept in its own hook rather than in RunsContext: strategies are owned rows
 * that arrive and disappear with the session, and folding them into the runs
 * store would mean every destination re-fetched them to render a nav item.
 *
 * A failed read is surfaced, never swallowed into an empty list — "you have no
 * strategies" and "we could not ask" are different facts, and only one of them
 * is fixed by making a strategy.
 */
export function useStrategyLibrary(enabled = true): StrategyLibrary {
  const [items, setItems] = useState<Strategy[]>([]);
  const [status, setStatus] = useState<LibraryStatus>(enabled ? 'loading' : 'ready');
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setStatus('loading');
    listStrategies()
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setError(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(caught instanceof ApiError ? caught.message : 'could not load your strategies');
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  // Create and replace are the same gesture to the user ("save"), so they are
  // one function here; which verb goes on the wire follows from whether the
  // strategy already has a server id.
  const save = useCallback(async (spec: StrategySpec, id: string | null) => {
    const saved = id === null ? await createStrategy(spec) : await replaceStrategy(id, spec);
    setItems((current) => {
      const without = current.filter((item) => item.id !== saved.id);
      return [saved, ...without];
    });
    return saved;
  }, []);

  const remove = useCallback(async (id: string) => {
    await deleteStrategy(id);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  return { items, status, error, reload, save, remove };
}
