import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  connectLive,
  disconnectLive,
  getLiveConnection,
  type LiveConnection,
  type LiveConnectRequest,
} from '../../api/client';

/** While a login is under way: quick, so "approve on your phone" appears promptly. */
const PENDING_POLL_MS = 3_000;
/** Otherwise: slow. A poll also tells the manager the user is still here. */
const IDLE_POLL_MS = 30_000;

const PENDING = new Set(['queued', 'starting', 'logging_in']);

export type ConnectionLoad =
  | { status: 'loading' }
  | { status: 'ready'; connection: LiveConnection }
  /** `unavailable`: live data is not set up on this server (503). */
  | { status: 'error'; message: string; unavailable: boolean };

function describe(caught: unknown): { message: string; unavailable: boolean } {
  if (caught instanceof ApiError) {
    return { message: caught.message, unavailable: caught.status === 503 };
  }
  return {
    message: caught instanceof Error ? caught.message : 'live connection unavailable',
    unavailable: false,
  };
}

/**
 * The user's own IBKR connection, polled while `enabled` (the Market tab's
 * live mode). There is no shared login: each user's live prices come from
 * their own account.
 */
export function useLiveConnection(enabled: boolean): {
  load: ConnectionLoad;
  connect: (body: LiveConnectRequest) => Promise<string | null>;
  disconnect: () => Promise<void>;
} {
  const [load, setLoad] = useState<ConnectionLoad>({ status: 'loading' });

  const refresh = useCallback(async () => {
    try {
      const connection = await getLiveConnection();
      setLoad({ status: 'ready', connection });
    } catch (caught) {
      setLoad({ status: 'error', ...describe(caught) });
    }
  }, []);

  const state = load.status === 'ready' ? load.connection.state : null;

  useEffect(() => {
    if (!enabled) return;
    void refresh();
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled) return;
    const every = state !== null && PENDING.has(state) ? PENDING_POLL_MS : IDLE_POLL_MS;
    const timer = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      void refresh();
    }, every);
    return () => window.clearInterval(timer);
  }, [enabled, state, refresh]);

  /** Resolves to an error message, or null once the request is accepted. */
  const connect = useCallback(async (body: LiveConnectRequest) => {
    try {
      const connection = await connectLive(body);
      setLoad({ status: 'ready', connection });
      return null;
    } catch (caught) {
      return describe(caught).message;
    }
  }, []);

  const disconnect = useCallback(async () => {
    try {
      const connection = await disconnectLive();
      setLoad({ status: 'ready', connection });
    } catch (caught) {
      setLoad({ status: 'error', ...describe(caught) });
    }
  }, []);

  return { load, connect, disconnect };
}
