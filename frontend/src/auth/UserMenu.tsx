import { LogOut, UserRound } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Button } from '../components/ui/button';
import { useOptionalAuth } from './AuthProvider';

/**
 * Who you are, and the way out.
 *
 * Renders nothing at all when there is no session — with
 * `QUANTLAB_AUTH_REQUIRED=false` there is no account to show, and a menu
 * offering to sign out of a session that does not exist would be a control
 * that lies about the system it is attached to.
 */
export function UserMenu() {
  const auth = useOptionalAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
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

  if (!auth || auth.status !== 'authenticated' || !auth.user) return null;

  return (
    <div ref={container} className="relative" data-testid="user-menu">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <UserRound size={16} strokeWidth={1.5} aria-hidden="true" />
        <span className="max-w-[16ch] truncate normal-case tracking-normal">
          {auth.user.email}
        </span>
      </Button>

      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 top-full z-20 mt-1 w-56 border border-border bg-card p-2 shadow-none"
        >
          <p className="break-all px-1 pb-2 text-[11px] text-muted-foreground">
            Signed in as <span className="font-mono text-foreground">{auth.user.email}</span>. Runs
            and strategies are private to this account.
          </p>
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
        </div>
      ) : null}
    </div>
  );
}
