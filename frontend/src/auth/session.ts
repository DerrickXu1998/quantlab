/**
 * Where the bearer token lives, outside React.
 *
 * The API client needs the token on every request and needs somewhere to
 * report a 401 to; AuthProvider needs to persist it and re-render on a change.
 * If the client imported the provider the two modules would be a cycle, so the
 * token sits in this third, React-free place and both sides talk to it.
 *
 * One key, and every localStorage access wrapped: a private window throws on
 * `localStorage` access rather than returning null, and an app that cannot log
 * in at all in a private window because a getter threw is a worse failure than
 * a session that simply does not survive a reload.
 */

const STORAGE_KEY = 'quantlab.auth.token';

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(token: string | null): void {
  try {
    if (token === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Storage is unavailable or full. The in-memory token still works for
    // this tab, which is the whole session the user asked for.
  }
}

let token: string | null = readStored();
const listeners = new Set<() => void>();

export function getToken(): string | null {
  return token;
}

export function setToken(next: string | null): void {
  if (token === next) return;
  token = next;
  writeStored(next);
  for (const listener of listeners) listener();
}

export function subscribeToken(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * A protected route answered 401: the token is dead, so drop it.
 *
 * Idempotent on purpose. Several requests in flight will all come back 401 at
 * once, and each one calling this must not produce a second teardown or a
 * second bounce to the login screen — the first clears the token and notifies,
 * and every later call sees a null token and returns without a notification.
 */
export function reportUnauthorized(): void {
  if (token === null) return;
  setToken(null);
}
