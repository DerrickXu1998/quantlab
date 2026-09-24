import { LogOut, Menu, Moon, Sun, UserRound, X, type LucideIcon } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useOptionalAuth } from '../auth/AuthProvider';
import { Button } from '../components/ui/button';
import { StatusBadge } from '../components/ui/status-badge';
import { cn } from '../lib/utils';
import { useTheme } from '../theme/ThemeProvider';
import type { Destination } from './router';

export interface NavItem {
  id: Destination;
  label: string;
  icon: LucideIcon;
  simulated?: string;
}

/**
 * The phone header: the product mark, where you are, and one button.
 *
 * Six destination icons plus the theme toggle and the account button still
 * measured wider than a 390px row wants, and icons with no labels made you
 * guess which one was which. So below `lg` they all move into this menu, where
 * each one has room for its label. The desktop row is not affected: the shell
 * renders this only when `useIsDesktop()` is false.
 */
export function MobileHeader({
  items,
  current,
  onNavigate,
}: {
  items: NavItem[];
  current: Destination;
  onNavigate: (id: Destination) => void;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const currentItem = items.find((item) => item.id === current);

  // Escape closes the menu and puts focus back on the button that opened it,
  // so a keyboard user is not left focused on something that just vanished.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      trigger.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    // Focus the page you are on, so the next Tab moves through the list from there.
    panel.current?.querySelector<HTMLElement>('[aria-current="page"]')?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <header className="relative z-30 flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-1">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="font-display text-sm tracking-[-0.02em]">QuantLab</span>
        {currentItem ? (
          <span className="truncate font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            {currentItem.label}
          </span>
        ) : null}
      </div>

      <Button
        ref={trigger}
        type="button"
        variant="ghost"
        size="icon"
        aria-label={open ? 'Close menu' : 'Open menu'}
        aria-expanded={open}
        aria-controls="mobile-menu"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? (
          <X size={20} strokeWidth={1.5} aria-hidden="true" />
        ) : (
          <Menu size={20} strokeWidth={1.5} aria-hidden="true" />
        )}
      </Button>

      {open ? (
        <>
          {/* Covers the page below the header: a tap outside the menu closes it,
              instead of landing on a control you can't see. 53px is the
              header: a 44px button, 4px of padding either side, 1px border. */}
          <div
            aria-hidden="true"
            data-testid="mobile-menu-backdrop"
            className="fixed inset-x-0 bottom-0 top-[53px] bg-background/70"
            onClick={() => setOpen(false)}
          />
          <div
            ref={panel}
            id="mobile-menu"
            className="absolute inset-x-0 top-full max-h-[calc(100dvh-53px)] animate-panel-in overflow-y-auto border-b border-border bg-background"
          >
            <nav aria-label="Destinations" className="flex flex-col p-2">
              {items.map((item) => {
                const active = item.id === current;
                return (
                  <Button
                    key={item.id}
                    type="button"
                    variant="ghost"
                    size="default"
                    aria-current={active ? 'page' : undefined}
                    title={item.simulated ?? item.label}
                    onClick={() => {
                      onNavigate(item.id);
                      setOpen(false);
                    }}
                    className={cn(
                      'w-full justify-start gap-3 px-3',
                      active ? 'bg-primary/10 text-primary hover:text-primary' : undefined,
                    )}
                  >
                    <item.icon size={20} strokeWidth={1.5} aria-hidden="true" />
                    <span>{item.label}</span>
                    {item.simulated ? (
                      <StatusBadge tone="simulated" title={item.simulated}>
                        sim
                      </StatusBadge>
                    ) : null}
                  </Button>
                );
              })}
            </nav>

            <div className="flex flex-col gap-2 border-t border-border p-2">
              <ThemeRow />
              <AccountRow onSignedOut={() => setOpen(false)} />
            </div>
          </div>
        </>
      ) : null}
    </header>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="flex items-center justify-between gap-3 px-3">{children}</div>;
}

function ThemeRow() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';
  const Icon = isDark ? Sun : Moon;
  return (
    <Button
      type="button"
      variant="ghost"
      onClick={toggleTheme}
      className="w-full justify-start gap-3 px-3"
    >
      <Icon size={20} strokeWidth={1.5} aria-hidden="true" />
      {isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    </Button>
  );
}

/** Mirrors UserMenu: shows nothing when there's no session to sign out of. */
function AccountRow({ onSignedOut }: { onSignedOut: () => void }) {
  const auth = useOptionalAuth();
  const [busy, setBusy] = useState(false);
  if (!auth || auth.status !== 'authenticated' || !auth.user) return null;

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-2" data-testid="mobile-account">
      <Row>
        <span className="flex min-w-0 items-center gap-3 text-[11px] text-muted-foreground">
          <UserRound size={20} strokeWidth={1.5} aria-hidden="true" className="shrink-0" />
          <span className="truncate font-mono text-foreground">{auth.user.email}</span>
        </span>
      </Row>
      <Button
        type="button"
        variant="outline"
        className="w-full"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await auth.logout();
          setBusy(false);
          onSignedOut();
        }}
      >
        <LogOut size={16} strokeWidth={1.5} aria-hidden="true" />
        {busy ? 'Signing out…' : 'Sign out'}
      </Button>
    </div>
  );
}
