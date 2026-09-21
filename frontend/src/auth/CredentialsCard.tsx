import { useState, type FormEvent } from 'react';
import { ApiError } from '../api/client';
import type { AuthCredentials } from '../api/auth';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Input, Label } from '../components/ui/field';
import { GrainOverlay } from '../quantlab/chrome/GrainOverlay';

export type AuthMode = 'login' | 'setup';

const COPY = {
  login: {
    heading: 'Sign in',
    blurb: 'Sign in to your workspace',
    submit: 'Sign in',
    pending: 'Signing in…',
    switchPrompt: 'First run?',
    switchLabel: 'Create the admin account',
  },
  setup: {
    heading: 'Create the admin account',
    blurb: 'No users yet — the first account becomes the administrator',
    submit: 'Create account',
    pending: 'Creating account…',
    switchPrompt: 'Already have an account?',
    switchLabel: 'Sign in',
  },
} as const;

function describeError(mode: AuthMode, error: unknown): string {
  if (error instanceof ApiError) {
    if (mode === 'login' && error.status === 401) return 'Invalid username or password.';
    if (error.status === 429) return 'Too many attempts. Wait a minute, then try again.';
    if (mode === 'setup' && error.status === 409) return 'That username is taken.';
    if (mode === 'setup' && (error.status === 401 || error.status === 403)) {
      return 'An account already exists. Sign in instead.';
    }
    if (error.status === 0) return 'QuantLab is unreachable. Check that the backend is running.';
    return error.message;
  }
  return 'Something went wrong. Try again.';
}

interface CredentialsCardProps {
  mode: AuthMode;
  onSubmit: (credentials: AuthCredentials) => Promise<void>;
  onSwitchMode: (mode: AuthMode) => void;
}

/**
 * The one credentials form, shared by sign-in and first-run setup: a centred
 * card over the grain, in the same terminal grammar as the rest of the app.
 */
export function CredentialsCard({ mode, onSubmit, onSwitchMode }: CredentialsCardProps) {
  const copy = COPY[mode];
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const name = username.trim();
    if (!name) {
      setError('Enter a username.');
      return;
    }
    if (password.length < 8) {
      setError('Passwords are at least 8 characters.');
      return;
    }
    setError(null);
    setPending(true);
    try {
      await onSubmit({ username: name, password });
      // On success the gate swaps screens; the pending state dies with it.
    } catch (cause) {
      setError(describeError(mode, cause));
      setPending(false);
    }
  }

  return (
    <div className="relative flex h-screen items-center justify-center bg-background px-4">
      <GrainOverlay />
      <div className="relative z-10 w-full max-w-xs">
        <div className="mb-6 text-center">
          <div className="font-display text-lg tracking-[-0.02em]">QuantLab</div>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            {copy.blurb}
          </p>
        </div>

        <Card>
          <CardContent className="p-4">
            <form noValidate onSubmit={handleSubmit} className="flex flex-col gap-3">
              <h1 className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                {copy.heading}
              </h1>
              <Label>
                Username
                <Input
                  data-testid="auth-username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoFocus
                  autoComplete="username"
                  maxLength={64}
                  required
                  disabled={pending}
                />
              </Label>
              <Label>
                Password
                <Input
                  data-testid="auth-password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  minLength={8}
                  required
                  disabled={pending}
                />
              </Label>
              {error ? (
                <p role="alert" className="text-[11px] text-destructive">
                  {error}
                </p>
              ) : null}
              <Button type="submit" disabled={pending} className="mt-1 w-full">
                {pending ? copy.pending : copy.submit}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="mt-4 text-center font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          {copy.switchPrompt}{' '}
          <button
            type="button"
            onClick={() => onSwitchMode(mode === 'login' ? 'setup' : 'login')}
            className="text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {copy.switchLabel}
          </button>
        </p>
      </div>
    </div>
  );
}
