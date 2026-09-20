import { useMemo, useState, type FormEvent } from 'react';
import { ApiError } from '../api/client';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/field';
import { GrainOverlay } from '../quantlab/chrome/GrainOverlay';
import { CornerTicks } from '../components/ui/corner-ticks';
import { useAuth } from './AuthProvider';

type Mode = 'login' | 'register';

/** The server's policy is authoritative; this is the same floor, said early. */
const MIN_PASSWORD_LENGTH = 8;

export interface PasswordStrength {
  /** 0–4. Nothing is gated on it — it is advice, not a second policy. */
  score: number;
  label: string;
  hint: string;
}

/**
 * A hint, deliberately not a gate.
 *
 * It counts length and character variety and says the one thing that would
 * most improve the password. A strength meter that blocks submission on its
 * own opinion ends up disagreeing with the server's real policy, and the user
 * is then stuck between two rules — so this one only ever advises.
 */
export function passwordStrength(password: string): PasswordStrength {
  if (password === '') {
    return { score: 0, label: 'Empty', hint: `At least ${MIN_PASSWORD_LENGTH} characters.` };
  }

  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((pattern) =>
    pattern.test(password),
  ).length;
  // Length is weighted as heavily as variety on purpose: a long passphrase of
  // plain words is genuinely harder to guess than a short one with a symbol
  // bolted on, and a meter that says otherwise teaches the wrong habit.
  const score = Math.min(
    4,
    (password.length >= MIN_PASSWORD_LENGTH ? 1 : 0) +
      (password.length >= 12 ? 1 : 0) +
      (password.length >= 16 ? 1 : 0) +
      (classes >= 3 ? 1 : 0) +
      (classes === 4 ? 1 : 0),
  );

  if (password.length < MIN_PASSWORD_LENGTH) {
    return {
      score,
      label: 'Too short',
      hint: `At least ${MIN_PASSWORD_LENGTH} characters — you have ${password.length}.`,
    };
  }
  if (score <= 1) {
    return { score, label: 'Weak', hint: 'Mix in a capital, a digit or a symbol.' };
  }
  if (score === 2) {
    return { score, label: 'Fair', hint: 'Longer beats more exotic — try 12 characters or more.' };
  }
  if (score === 3) {
    return { score, label: 'Good', hint: 'A passphrase of a few unrelated words is stronger still.' };
  }
  return { score, label: 'Strong', hint: 'Long and varied. Nothing else to add.' };
}

function emailError(email: string): string | null {
  if (email.trim() === '') return 'Email is required.';
  // Deliberately loose: the address is verified by the server accepting it,
  // and an over-strict pattern here rejects addresses that are genuinely valid.
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return 'That is not an email address.';
  return null;
}

function passwordError(password: string, mode: Mode): string | null {
  if (password === '') return 'Password is required.';
  if (mode === 'register' && password.length < MIN_PASSWORD_LENGTH) {
    return `At least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  return null;
}

/** Turns the API's status codes into something a person can act on. */
function messageFor(error: unknown, mode: Mode): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Email or password is incorrect.';
    if (error.status === 409) return 'That email is already registered. Sign in instead.';
    if (error.status === 422) return error.message || 'That password does not meet the policy.';
    if (error.status === 429) return 'Too many attempts for that email. Wait a minute and retry.';
    if (error.status === 0) return error.message;
    return error.message;
  }
  return mode === 'login' ? 'Could not sign in.' : 'Could not create the account.';
}

const MICRO = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

function StrengthMeter({ password }: { password: string }) {
  const strength = passwordStrength(password);
  return (
    <div data-testid="password-strength" className="space-y-1">
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="flex flex-1 gap-1">
          {[0, 1, 2, 3].map((index) => (
            <span
              key={index}
              className={`h-px flex-1 ${
                index < strength.score ? 'bg-primary' : 'bg-border'
              } transition-colors`}
            />
          ))}
        </span>
        <span className={MICRO}>{strength.label}</span>
      </div>
      <p className="text-[11px] text-muted-foreground">{strength.hint}</p>
    </div>
  );
}

/**
 * The one screen you can reach without a session.
 *
 * Sign in and Create account are tabs on a single form rather than two routes:
 * the fields are identical, and a person who mistypes their email into the
 * wrong one should be able to switch without retyping anything.
 *
 * Field errors appear once a field has been left or the form submitted, never
 * on the first keystroke — validating a half-typed email as you type is how a
 * form manages to be wrong about every address for as long as it is being
 * entered.
 */
export function LoginScreen() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [touched, setTouched] = useState<{ email: boolean; password: boolean }>({
    email: false,
    password: false,
  });
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const errors = useMemo(
    () => ({ email: emailError(email), password: passwordError(password, mode) }),
    [email, password, mode],
  );
  const showEmailError = (touched.email || submitted) && errors.email;
  const showPasswordError = (touched.password || submitted) && errors.password;
  const invalid = Boolean(errors.email || errors.password);

  const switchTo = (next: Mode) => {
    if (next === mode) return;
    setMode(next);
    setError(null);
    setSubmitted(false);
    // Password rules differ between the tabs, so a password that was fine for
    // signing in should not arrive at Create account already marked invalid.
    setTouched((current) => ({ ...current, password: false }));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (invalid || pending) return;
    setPending(true);
    setError(null);
    try {
      const credentials = { email: email.trim(), password };
      if (mode === 'login') await login(credentials);
      else await register(credentials);
      // On success this screen unmounts: the shell renders the app instead.
    } catch (caught: unknown) {
      setError(messageFor(caught, mode));
      setPending(false);
    }
  };

  const tab = (value: Mode, label: string) => (
    <button
      key={value}
      type="button"
      role="tab"
      id={`auth-tab-${value}`}
      aria-selected={mode === value}
      aria-controls="auth-panel"
      onClick={() => switchTo(value)}
      className={`flex-1 border-b-2 px-3 py-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary ${
        mode === value
          ? 'border-b-primary text-primary'
          : 'border-b-transparent text-muted-foreground hover:text-foreground'
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background px-4">
      <GrainOverlay />

      <main className="relative z-10 w-full max-w-sm" data-testid="login-screen">
        <div className="mb-6 text-center">
          <p className="font-display text-2xl tracking-[-0.02em]">QuantLab</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Signal research on stored daily bars. Your runs and strategies are yours alone.
          </p>
        </div>

        <div className="relative border border-border bg-card">
          <CornerTicks />

          <div role="tablist" aria-label="Authentication" className="flex border-b border-border">
            {tab('login', 'Sign in')}
            {tab('register', 'Create account')}
          </div>

          <form
            id="auth-panel"
            role="tabpanel"
            aria-labelledby={`auth-tab-${mode}`}
            className="space-y-4 p-4"
            onSubmit={submit}
            noValidate
          >
            <div className="space-y-1">
              <label className={MICRO} htmlFor="auth-email">
                Email
              </label>
              <Input
                id="auth-email"
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                aria-invalid={showEmailError ? true : undefined}
                aria-describedby={showEmailError ? 'auth-email-error' : undefined}
                onChange={(event) => setEmail(event.target.value)}
                onBlur={() => setTouched((current) => ({ ...current, email: true }))}
              />
              {showEmailError ? (
                <p id="auth-email-error" role="alert" className="text-[11px] text-destructive">
                  {errors.email}
                </p>
              ) : null}
            </div>

            <div className="space-y-1">
              <label className={MICRO} htmlFor="auth-password">
                Password
              </label>
              <Input
                id="auth-password"
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                value={password}
                aria-invalid={showPasswordError ? true : undefined}
                aria-describedby={showPasswordError ? 'auth-password-error' : undefined}
                onChange={(event) => setPassword(event.target.value)}
                onBlur={() => setTouched((current) => ({ ...current, password: true }))}
              />
              {showPasswordError ? (
                <p id="auth-password-error" role="alert" className="text-[11px] text-destructive">
                  {errors.password}
                </p>
              ) : null}
              {mode === 'register' ? <StrengthMeter password={password} /> : null}
            </div>

            {/* One error region, always in the DOM's reading order at the same
                place, so a screen reader hears the failure where the button is. */}
            {error ? (
              <p
                role="alert"
                data-testid="auth-error"
                className="border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-[11px] text-destructive"
              >
                {error}
              </p>
            ) : null}

            <Button type="submit" disabled={pending} className="w-full">
              {pending
                ? mode === 'login'
                  ? 'Signing in…'
                  : 'Creating…'
                : mode === 'login'
                  ? 'Sign in'
                  : 'Create account'}
            </Button>

            <p className="text-[11px] text-muted-foreground">
              {mode === 'login'
                ? 'No account yet? Create one — it takes an email and a password, and nothing else.'
                : 'Creating an account gives you a private workspace: only you can read, rename or delete your runs.'}
            </p>
          </form>
        </div>
      </main>
    </div>
  );
}
