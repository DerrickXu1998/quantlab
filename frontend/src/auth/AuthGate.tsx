import { Hourglass } from 'lucide-react';
import type { ReactNode } from 'react';
import { useDataset } from '../api/DatasetProvider';
import { EmptyState } from '../components/ui/empty-state';
import { useAuth } from './AuthProvider';
import { LoginScreen } from './LoginScreen';

function Booting({ label }: { label: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <EmptyState icon={Hourglass} title={label} role="status" />
    </div>
  );
}

/**
 * Local-dev escape hatch: `VITE_AUTH_BYPASS=true npm run dev` skips the login
 * screen, for checking UI against a backend with no auth (or an older image
 * that predates it). `import.meta.env.DEV` is false in `vite build`, so the
 * whole branch is dead code in production however the variable is set.
 */
const DEV_AUTH_BYPASS = import.meta.env.DEV && import.meta.env.VITE_AUTH_BYPASS === 'true';

/**
 * Whether the app is reachable without signing in, and what to show if not.
 *
 * `QUANTLAB_AUTH_REQUIRED=false` is a supported mode, not a hack — it is what
 * keeps `make up` a one-command demo with no account to create — so the shell
 * asks the API which mode it is in (`/health.auth_required`) instead of
 * assuming. Guessing "required" would put a login wall in front of a backend
 * that would have answered every request anyway.
 *
 * The three uncertain cases each get their own answer rather than a shared
 * spinner:
 *   - health has not answered yet: wait, because gating on an unknown would
 *     flash a login screen at a demo that needs none;
 *   - health cannot be reached: do not gate. The destinations have their own
 *     "backend unreachable" states, and those say far more than a login form
 *     that is also about to fail;
 *   - a stored token is still being validated: wait, rather than rendering the
 *     app around a session that may already be revoked.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const dataset = useDataset();
  const { status } = useAuth();

  if (DEV_AUTH_BYPASS) return <>{children}</>;
  if (dataset.status === 'loading') return <Booting label="Contacting the API…" />;

  const authRequired = dataset.status === 'ready' && dataset.health.auth_required !== false;
  if (!authRequired) return <>{children}</>;

  if (status === 'checking') return <Booting label="Restoring your session…" />;
  if (status !== 'authenticated') return <LoginScreen />;

  return <>{children}</>;
}
