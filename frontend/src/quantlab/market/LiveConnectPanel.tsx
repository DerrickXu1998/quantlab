import { Hourglass, KeyRound, PlugZap, Smartphone } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import type { LiveConnection } from '../../api/client';
import { Button } from '../../components/ui/button';
import { Input, Select } from '../../components/ui/field';
import { EmptyState } from '../chrome/EmptyState';
import type { ConnectionLoad } from './useLiveConnection';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

type Mode = 'paper' | 'live';

/**
 * Connect the user's own IBKR account -- the only way to live prices.
 *
 * There is no shared login: an account's market data is licensed to its
 * holder, so every user brings theirs. The password field is cleared the
 * moment the form is sent; the password goes to the user's own gateway and
 * quantlab keeps no copy.
 */
export function LiveConnectPanel({
  load,
  onConnect,
  onCancel,
}: {
  load: ConnectionLoad;
  onConnect: (body: {
    username: string;
    password: string;
    trading_mode: Mode;
  }) => Promise<string | null>;
  onCancel: () => void;
}) {
  if (load.status === 'loading') {
    return (
      <EmptyState
        icon={Hourglass}
        title="Checking your IBKR connection…"
        role="status"
        testId="live-conn-loading"
        className="min-h-0 flex-1"
      />
    );
  }
  if (load.status === 'error') {
    return (
      <EmptyState
        icon={PlugZap}
        tone="error"
        title={
          load.unavailable
            ? 'Live data is not set up on this server'
            : 'Could not read your IBKR connection'
        }
        detail={load.unavailable ? 'An administrator starts it with `make live-up`.' : load.message}
        testId="live-conn-error"
        className="min-h-0 flex-1"
      />
    );
  }
  const connection = load.connection;
  if (
    connection.state === 'queued' ||
    connection.state === 'starting' ||
    connection.state === 'logging_in'
  ) {
    return <Pending connection={connection} onCancel={onCancel} />;
  }
  return <ConnectForm connection={connection} onConnect={onConnect} />;
}

function Pending({ connection, onCancel }: { connection: LiveConnection; onCancel: () => void }) {
  const queued = connection.state === 'queued';
  const twoFactor = (connection.detail ?? '').includes('IB Key');
  return (
    <div
      data-testid="live-conn-pending"
      data-state={connection.state}
      className="flex min-h-0 flex-1 items-center justify-center p-6"
    >
      <div className="w-full max-w-md space-y-3 border border-border bg-card p-5" role="status">
        <div className="flex items-center gap-2">
          {twoFactor ? (
            <Smartphone size={20} strokeWidth={1.5} aria-hidden="true" className="text-primary" />
          ) : (
            <Hourglass
              size={20}
              strokeWidth={1.5}
              aria-hidden="true"
              className="text-muted-foreground"
            />
          )}
          <h2 className="font-display text-lg">
            {queued
              ? `All live-data slots are in use — you're #${connection.queue_position ?? '?'} in line`
              : twoFactor
                ? 'Approve the login on your phone'
                : `Connecting ${connection.ib_username ?? 'your account'} (${connection.trading_mode ?? 'paper'})…`}
          </h2>
        </div>
        <p className="text-sm text-muted-foreground" data-testid="live-conn-detail">
          {queued
            ? 'Your gateway starts as soon as a slot frees up. Keep this tab open; you will not need to sign in again.'
            : connection.detail}
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function ConnectForm({
  connection,
  onConnect,
}: {
  connection: LiveConnection;
  onConnect: (body: {
    username: string;
    password: string;
    trading_mode: Mode;
  }) => Promise<string | null>;
}) {
  const [username, setUsername] = useState(connection.ib_username ?? '');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState<Mode>((connection.trading_mode as Mode | null) ?? 'paper');
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const failed = connection.state === 'failed';

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password) return;
    const secret = password;
    // Gone from the page as soon as it is sent.
    setPassword('');
    setSending(true);
    setError(await onConnect({ username: username.trim(), password: secret, trading_mode: mode }));
    setSending(false);
  };

  return (
    <div
      data-testid="live-connect"
      className="flex min-h-0 flex-1 items-start justify-center overflow-y-auto p-6"
    >
      <form
        onSubmit={submit}
        className="w-full max-w-md space-y-4 border border-border bg-card p-5"
        aria-label="Connect your IBKR account"
      >
        <div className="flex items-center gap-2">
          <KeyRound size={20} strokeWidth={1.5} aria-hidden="true" className="text-primary" />
          <h2 className="font-display text-lg">Connect your IBKR account for live prices</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Live prices come from your own Interactive Brokers account — an account's market data is
          licensed to its holder, so QuantLab has no shared login. Your account needs a US
          market-data subscription.
        </p>

        {failed && connection.detail ? (
          <p
            role="alert"
            data-testid="live-conn-failed"
            className="border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            {connection.detail}
          </p>
        ) : null}
        {error ? (
          <p
            role="alert"
            data-testid="live-conn-submit-error"
            className="border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        <div className="space-y-1">
          <label className={MICRO} htmlFor="ibkr-username">
            IBKR username
          </label>
          <Input
            id="ibkr-username"
            autoComplete="off"
            spellCheck={false}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label className={MICRO} htmlFor="ibkr-password">
            IBKR password
          </label>
          <Input
            id="ibkr-password"
            type="password"
            autoComplete="off"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label className={MICRO} htmlFor="ibkr-mode">
            Account
          </label>
          <Select id="ibkr-mode" value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
            <option value="paper">Paper</option>
            <option value="live">Live</option>
          </Select>
          <p className="text-xs text-muted-foreground" data-testid="live-conn-mode-hint">
            {mode === 'paper'
              ? 'No 2FA. In Client Portal, turn on "share market data with paper account" first.'
              : "You'll approve an IB Key notification on your phone."}
          </p>
        </div>

        <ul
          className="list-disc space-y-1 pl-5 text-xs text-muted-foreground"
          data-testid="live-conn-terms"
        >
          <li>
            Your password is passed to a gateway that runs only for you and is not stored. You will
            enter it again after a disconnect or IBKR's weekly re-login.
          </li>
          <li>
            The gateway is read-only: QuantLab cannot place orders through it. Using a secondary
            IBKR user with trading disabled is safer still.
          </li>
          <li>It stops after 15 minutes without a live chart open.</li>
        </ul>

        <Button type="submit" disabled={sending || !username.trim() || !password}>
          {sending ? 'Connecting…' : 'Connect'}
        </Button>
      </form>
    </div>
  );
}
