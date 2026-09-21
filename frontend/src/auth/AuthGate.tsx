import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  fetchCurrentUser,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  type AuthCredentials,
  type UserPublic,
} from '../api/auth';
import { ApiError } from '../api/client';
import { onSessionExpired } from '../api/session';
import { GrainOverlay } from '../quantlab/chrome/GrainOverlay';
import { CredentialsCard, type AuthMode } from './CredentialsCard';

type GateState =
  | { status: 'checking' }
  | { status: 'disabled' }
  | { status: 'unauthenticated'; mode: AuthMode }
  | { status: 'authenticated'; user: UserPublic };

interface AuthContextValue {
  /** The signed-in user; null when auth is disabled or outside the gate. */
  user: UserPublic | null;
  logout: () => void;
}

/**
 * The default context is "no session chrome": surfaces rendered without the
 * gate (tests, Storybook-style harnesses) behave exactly as they did before
 * auth existed.
 */
const AuthContext = createContext<AuthContextValue>({ user: null, logout: () => {} });

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

/**
 * The mount-chain gate. On load it asks GET /auth/me who is calling, once:
 *
 *   200 → authenticated; the shell renders.
 *   404 → the backend runs with QUANTLAB_AUTH=off; the shell renders with no
 *         session chrome (the auth routes do not exist in that mode).
 *   401 → sign-in. The 401 body carries no "setup_required" marker, so the
 *         gate cannot tell zero-users apart from a plain expired session; the
 *         first-run setup form is one click away from the sign-in card, and a
 *         register attempt that arrives too late (409/401/403) says so inline.
 *
 * After the initial check, any 401 reported by the API client (an expired
 * session on a data endpoint) collapses the app back to the sign-in card.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>({ status: 'checking' });

  useEffect(() => {
    let cancelled = false;
    fetchCurrentUser()
      .then((user) => {
        if (!cancelled) setState({ status: 'authenticated', user });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          setState({ status: 'disabled' });
        } else {
          setState({ status: 'unauthenticated', mode: 'login' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(
    () => onSessionExpired(() => setState({ status: 'unauthenticated', mode: 'login' })),
    [],
  );

  const login = useCallback(async (credentials: AuthCredentials) => {
    const user = await apiLogin(credentials);
    setState({ status: 'authenticated', user });
  }, []);

  const setup = useCallback(async (credentials: AuthCredentials) => {
    await apiRegister(credentials);
    // Register sets no cookie; sign straight in with the same credentials.
    const user = await apiLogin(credentials);
    setState({ status: 'authenticated', user });
  }, []);

  const logout = useCallback(() => {
    void apiLogout()
      .catch(() => {
        // The cookie is gone or the backend is down; either way the session
        // is over as far as the UI is concerned.
      })
      .finally(() => setState({ status: 'unauthenticated', mode: 'login' }));
  }, []);

  const contextValue = useMemo<AuthContextValue>(
    () => ({ user: state.status === 'authenticated' ? state.user : null, logout }),
    [state, logout],
  );

  if (state.status === 'authenticated' || state.status === 'disabled') {
    return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>;
  }

  if (state.status === 'checking') {
    return (
      <div
        role="status"
        aria-label="Checking session"
        className="relative flex h-screen items-center justify-center bg-background"
      >
        <GrainOverlay />
        <span className="relative z-10 h-2 w-2 animate-pulse border border-primary bg-primary/20" />
      </div>
    );
  }

  return (
    <AuthContext.Provider value={contextValue}>
      <CredentialsCard
        key={state.mode}
        mode={state.mode}
        onSubmit={state.mode === 'login' ? login : setup}
        onSwitchMode={(mode) => setState({ status: 'unauthenticated', mode })}
      />
    </AuthContext.Provider>
  );
}
