import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import {
  getMe,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
} from '../api/client';
import type { AuthUser, Credentials } from '../api/types';
import { getToken, setToken, subscribeToken } from './session';

export type AuthStatus =
  /** A token was found and `/auth/me` has not answered yet. */
  | 'checking'
  /** No session. The shell shows the login screen when auth is required. */
  | 'anonymous'
  | 'authenticated';

export interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  status: AuthStatus;
  login: (credentials: Credentials) => Promise<void>;
  register: (credentials: Credentials) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * The session, held once, above everything.
 *
 * The token itself lives in `session.ts` rather than in state: the API client
 * has to read it on every request and has to be able to drop it on a 401
 * without going through React, and this provider subscribes to that store so
 * a 401 anywhere in the app lands here as a re-render into `anonymous`. That
 * is the whole redirect mechanism — there is no imperative bounce to get stuck
 * in a loop, because the login screen is simply what "no session" renders as.
 *
 * On boot a stored token is *validated*, not trusted: a token from last month
 * may already have been revoked, and rendering the whole app around a dead
 * session only to have every panel fail its own 401 is a much worse first
 * screen than the login form.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const token = useSyncExternalStore(subscribeToken, getToken, getToken);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>(() =>
    getToken() === null ? 'anonymous' : 'checking',
  );

  // Kept in a ref as well as in state so the effect below can tell "we just
  // signed in and already have the user" from "we booted with a stored token
  // and have never seen the user" — the two differ by one network call, and
  // state would not have settled in time to make the distinction.
  const userRef = useRef<AuthUser | null>(null);

  useEffect(() => {
    if (token === null) {
      userRef.current = null;
      setUser(null);
      setStatus('anonymous');
      return;
    }
    if (userRef.current !== null) {
      setStatus('authenticated');
      return;
    }

    let cancelled = false;
    setStatus('checking');
    getMe()
      .then((me) => {
        if (cancelled) return;
        userRef.current = me;
        setUser(me);
        setStatus('authenticated');
      })
      .catch(() => {
        // A 401 has already cleared the token in the client, which re-enters
        // this effect with `token === null`. Anything else — an unreachable
        // backend — leaves the token alone: it may still be good, and
        // throwing away a valid session because the server blinked would
        // silently sign the user out.
        if (!cancelled) setStatus('anonymous');
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const adopt = useCallback((session: { user: AuthUser; token: string }) => {
    userRef.current = session.user;
    setUser(session.user);
    setToken(session.token);
    setStatus('authenticated');
  }, []);

  const login = useCallback(
    async (credentials: Credentials) => {
      adopt(await apiLogin(credentials));
    },
    [adopt],
  );

  const register = useCallback(
    async (credentials: Credentials) => {
      adopt(await apiRegister(credentials));
    },
    [adopt],
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // The server-side revoke failed or the session was already dead. The
      // local half of a logout is not negotiable either way: drop the token.
    }
    userRef.current = null;
    setUser(null);
    setToken(null);
    setStatus('anonymous');
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, status, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * The session when there is a provider, and null when there is not.
 *
 * The shell header is rendered in isolation by several existing tests, and a
 * user menu is not worth making every one of them wrap a provider — a header
 * with nowhere to read a session from simply has no user menu.
 */
export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
}
