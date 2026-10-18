import { KeyRound, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import {
  deleteIbkrCredentials,
  putIbkrCredentials,
  type LiveConnection,
  type UserSettingsDocument,
} from '../api/client';
import { Button } from '../components/ui/button';
import { Input, Select } from '../components/ui/field';
import { ButtonGroup } from '../components/ui/layout';
import { useSettings } from './SettingsProvider';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

function Section({
  title,
  children,
  testId,
}: {
  title: string;
  children: ReactNode;
  testId: string;
}) {
  return (
    <section
      data-testid={testId}
      className="space-y-3 border-b border-border px-4 py-4 last:border-b-0"
    >
      <h3 className={MICRO}>{title}</h3>
      {children}
    </section>
  );
}

function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-sm">{label}</span>
      <ButtonGroup label={label}>
        {options.map((option) => (
          <Button
            key={option.id}
            type="button"
            size="sm"
            variant={value === option.id ? 'default' : 'outline'}
            aria-pressed={value === option.id}
            onClick={() => onChange(option.id)}
          >
            {option.label}
          </Button>
        ))}
      </ButtonGroup>
    </div>
  );
}

const CONNECTION_LABEL: Record<LiveConnection['state'], string> = {
  none: 'Not connected',
  queued: 'Queued for a live-data slot',
  starting: 'Starting your gateway',
  logging_in: 'Logging in',
  connected: 'Connected',
  failed: 'Login failed',
};

/**
 * Everything the user configures for themselves, in one place: opened from
 * the account menu. Saved to the account (GET/PATCH /me/settings), so it
 * follows the user to any browser.
 */
export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const settings = useSettings();
  const closeButton = useRef<HTMLButtonElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    closeButton.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const load = settings?.load;

  const save = async (patch: Parameters<NonNullable<typeof settings>['update']>[0]) => {
    if (!settings) return;
    setError(await settings.update(patch));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-background/80 px-4 py-8"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        data-testid="settings-dialog"
        className="flex max-h-full w-full max-w-xl flex-col rounded-sm border border-border bg-card"
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
          <h2 id="settings-title" className={`${MICRO} flex-1`}>
            Settings
          </h2>
          <Button
            ref={closeButton}
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Close settings"
            onClick={onClose}
          >
            <X size={16} strokeWidth={1.5} aria-hidden="true" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {!load || load.status === 'loading' ? (
            <p role="status" className="px-4 py-6 text-sm text-muted-foreground">
              Loading your settings…
            </p>
          ) : load.status === 'error' ? (
            <p role="alert" className="px-4 py-6 text-sm text-destructive">
              Could not load your settings: {load.message}
            </p>
          ) : (
            <Body document={load.document} save={save} />
          )}
          {error ? (
            <p
              role="alert"
              data-testid="settings-error"
              className="mx-4 mb-4 text-sm text-destructive"
            >
              Not saved: {error}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Body({
  document,
  save,
}: {
  document: UserSettingsDocument;
  save: (
    patch: Parameters<NonNullable<ReturnType<typeof useSettings>>['update']>[0],
  ) => Promise<void>;
}) {
  const { account, settings } = document;
  return (
    <>
      <Section title="Account" testId="settings-account">
        <p className="text-sm">
          {account.email ? (
            <>
              Signed in as <span className="font-mono">{account.email}</span>. These settings are
              this account's, on any browser.
            </>
          ) : (
            'Local account: sign-in is off on this server, so everyone using it shares these settings.'
          )}
        </p>
      </Section>

      <Section title="Appearance" testId="settings-appearance">
        <Choice
          label="Theme"
          value={settings.appearance.theme}
          options={[
            { id: 'dark', label: 'Dark' },
            { id: 'light', label: 'Light' },
          ]}
          onChange={(theme) => void save({ appearance: { theme } })}
        />
      </Section>

      <Section title="Market" testId="settings-market">
        <Choice
          label="Open the Market tab on"
          value={settings.market.default_data}
          options={[
            { id: 'historical', label: 'Historical' },
            { id: 'live', label: 'Live intraday' },
          ]}
          onChange={(default_data) => void save({ market: { default_data } })}
        />
        <div className="space-y-1">
          <p className="text-sm">Saved ticker lists</p>
          {settings.market.lists.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              None yet. Save one from the Market tab's universe list.
            </p>
          ) : (
            <ul
              data-testid="settings-lists"
              className="divide-y divide-border border border-border"
            >
              {settings.market.lists.map((list) => (
                <li key={list.name} className="flex items-center gap-2 px-2 py-1 text-sm">
                  <span className="min-w-0 flex-1 truncate">{list.name}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {list.symbols.length} tickers
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Delete list ${list.name}`}
                    onClick={() =>
                      void save({
                        market: {
                          lists: settings.market.lists.filter((l) => l.name !== list.name),
                        },
                      })
                    }
                  >
                    <Trash2 size={16} strokeWidth={1.5} aria-hidden="true" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      <IbkrSection document={document} />
    </>
  );
}

function IbkrSection({ document }: { document: UserSettingsDocument }) {
  const settings = useSettings();
  const { ibkr } = document.settings;
  const connection = document.ibkr_connection;
  const [username, setUsername] = useState(ibkr.username ?? '');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState<'paper' | 'live'>(ibkr.trading_mode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (call: () => Promise<UserSettingsDocument>) => {
    setBusy(true);
    setError(null);
    try {
      settings?.replace(await call());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'request failed');
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password) return;
    const secret = password;
    // Off the page as soon as it is sent; the server stores it nowhere either.
    setPassword('');
    await run(() =>
      putIbkrCredentials({ username: username.trim(), password: secret, trading_mode: mode }),
    );
  };

  const live = connection !== null;
  const connected = connection?.state === 'connected';

  return (
    <Section title="IBKR · live market data" testId="settings-ibkr">
      <p className="text-xs text-muted-foreground">
        Live prices come from your own Interactive Brokers login. Your username and account type are
        saved here. Your password is never saved in QuantLab's database or shown again: it is kept
        only by a gateway that runs for you (on the server, with that gateway's container), which
        stays on until you disconnect — disconnecting deletes the gateway and the password with
        it. The gateway is read-only.
      </p>

      <p data-testid="settings-ibkr-status" className="text-sm">
        {!live ? (
          'Live data is not set up on this server.'
        ) : (
          <>
            <span className={connected ? 'text-primary' : undefined}>
              {CONNECTION_LABEL[connection.state]}
            </span>
            {connection.ib_username ? (
              <span className="text-muted-foreground">
                {' '}
                · {connection.ib_username} ({connection.trading_mode})
              </span>
            ) : null}
            {connection.state === 'queued' && connection.queue_position ? (
              <span className="text-muted-foreground"> · #{connection.queue_position} in line</span>
            ) : null}
            {connection.detail ? (
              <span className="block text-xs text-muted-foreground">{connection.detail}</span>
            ) : null}
          </>
        )}
      </p>

      {error ? (
        <p role="alert" data-testid="settings-ibkr-error" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <form onSubmit={submit} className="space-y-3" aria-label="IBKR credentials">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label className={MICRO} htmlFor="settings-ibkr-username">
              IBKR username
            </label>
            <Input
              id="settings-ibkr-username"
              autoComplete="off"
              spellCheck={false}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <label className={MICRO} htmlFor="settings-ibkr-mode">
              Account
            </label>
            <Select
              id="settings-ibkr-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as 'paper' | 'live')}
            >
              <option value="paper">Paper</option>
              <option value="live">Live</option>
            </Select>
          </div>
        </div>
        <div className="space-y-1">
          <label className={MICRO} htmlFor="settings-ibkr-password">
            IBKR password
          </label>
          <Input
            id="settings-ibkr-password"
            type="password"
            autoComplete="off"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" disabled={!live || busy || !username.trim() || !password}>
            <KeyRound size={16} strokeWidth={1.5} aria-hidden="true" />
            {connected ? 'Reconnect' : 'Save & connect'}
          </Button>
          {live && connection.state !== 'none' ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void run(() => deleteIbkrCredentials())}
            >
              Disconnect
            </Button>
          ) : null}
          {ibkr.username ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const document = await deleteIbkrCredentials(true);
                  setUsername('');
                  setMode('paper');
                  return document;
                })
              }
            >
              Forget login
            </Button>
          ) : null}
        </div>
      </form>
    </Section>
  );
}
