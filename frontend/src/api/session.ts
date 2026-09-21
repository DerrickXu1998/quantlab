/**
 * Session-expiry signalling. The API client reports any 401 from a non-auth
 * endpoint here; the AuthGate subscribes and collapses back to the sign-in
 * screen. Kept as a tiny pub/sub so the client stays free of React and the
 * gate stays free of fetch details.
 */

type SessionExpiredListener = () => void;

const listeners = new Set<SessionExpiredListener>();

/** Subscribe to session expiry. Returns the unsubscribe function. */
export function onSessionExpired(listener: SessionExpiredListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Called by the API client when a data endpoint answers 401. */
export function reportSessionExpired(): void {
  for (const listener of listeners) listener();
}
