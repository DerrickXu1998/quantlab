import { LogOut, Settings, UserRound } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useDataset } from '../api/DatasetProvider';
import { Button } from '../components/ui/button';
import { SettingsDialog } from '../settings/SettingsDialog';
import { useOptionalAuth } from './AuthProvider';

/**
 * Who you are, your settings, and the way out.
 *
 * With a session it names the account and offers Settings and Sign out. With
 * sign-in off (`QUANTLAB_AUTH_REQUIRED=false`) there is still one built-in
 * account whose settings can be changed, so the menu shows that -- but never
 * a Sign out for a session that does not exist.
 */
export function UserMenu() {
  const auth = useOptionalAuth();
  const dataset = useDataset();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  // Closes on Escape and on a click elsewhere: the two gestures every menu is
  // expected to answer to, and the ones a bespoke popover usually forgets.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onClick = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('mousedown', onClick);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  const signedIn = auth?.status === 'authenticated' && auth.user ? auth.user : null;
  const signInOff = dataset.status === 'ready' && dataset.health.auth_required === false;
  if (!signedIn && !signInOff) return null;
  const label = signedIn ? signedIn.email : 'Local account';

  return (
    <div ref={container} className="relative" data-testid="user-menu">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-haspopup="menu"
        aria-expanded={open}
        // The email is hidden below 1,440px so the header's full row fits a
        // 1,280px laptop, so the name has to come from here.
        aria-label={`Account: ${label}`}
        title={label}
        onClick={() => setOpen((current) => !current)}
      >
        <UserRound size={16} strokeWidth={1.5} aria-hidden="true" />
        <span className="hidden max-w-[16ch] truncate normal-case tracking-normal min-[1440px]:inline">
          {label}
        </span>
      </Button>

      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 top-full z-20 mt-1 w-56 border border-border bg-card p-2 shadow-none"
        >
          {signedIn ? (
            <p className="break-all px-1 pb-2 text-xs text-muted-foreground">
              Signed in as <span className="font-mono text-foreground">{signedIn.email}</span>. Runs
              and strategies are private to this account.
            </p>
          ) : (
            <p className="px-1 pb-2 text-xs text-muted-foreground">
              Sign-in is off on this server: everyone shares the local account.
            </p>
          )}
          <Button
            type="button"
            role="menuitem"
            variant="ghost"
            size="sm"
            className="mb-1 w-full justify-start"
            onClick={() => {
              setOpen(false);
              setSettingsOpen(true);
            }}
          >
            <Settings size={16} strokeWidth={1.5} aria-hidden="true" />
            Settings
          </Button>
          {signedIn && auth ? (
            <Button
              type="button"
              role="menuitem"
              variant="outline"
              size="sm"
              className="w-full"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                await auth.logout();
                setBusy(false);
                setOpen(false);
              }}
            >
              <LogOut size={16} strokeWidth={1.5} aria-hidden="true" />
              {busy ? 'Signing out…' : 'Sign out'}
            </Button>
          ) : null}
        </div>
      ) : null}
      {settingsOpen ? <SettingsDialog onClose={() => setSettingsOpen(false)} /> : null}
    </div>
  );
}
