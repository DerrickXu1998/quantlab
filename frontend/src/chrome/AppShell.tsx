import { ChartLine, FlaskConical, History, LayoutDashboard, Search } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { UserMenu } from '../auth/UserMenu';
import { GlossaryButton } from '../glossary/GlossaryButton';
import { DataSourceBanner } from '../components/DataSourceBanner';
import { Button } from '../components/ui/button';
import { ResearchPage } from '../pages/ResearchPage';
import { GrainOverlay } from '../quantlab/chrome/GrainOverlay';
import { FEATURED_SYMBOLS, useWatchlist } from '../quantlab/data/useWatchlist';
import { LiveFeedProvider } from '../quantlab/feed/LiveFeedProvider';
import { TickerTape } from '../quantlab/panels/TickerTape';
import { MarketView } from '../quantlab/views/MarketView';
import { OverviewView } from '../quantlab/views/OverviewView';
import { ReplayView } from '../quantlab/views/ReplayView';
import { StrategyLabView } from '../quantlab/views/StrategyLabView';
import { ThemeToggle } from '../theme/ThemeToggle';
import { DatasetBadge } from '../workbench/DatasetBadge';
import { cn } from '../lib/utils';
import { useOptionalRuns } from '../runs/RunsContext';
import { RunNotices } from '../runs/RunNotices';
import { CommandPalette, useCommandPaletteShortcut } from './CommandPalette';
import { MobileHeader, type NavItem } from './MobileMenu';
import { navigate, replaceRoute, useRoute } from './router';
import { useIsDesktop } from './useMediaQuery';
import { useRowFits } from './useRowFits';

const NAV: NavItem[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'research', label: 'Research', icon: Search },
  { id: 'strategies', label: 'Strategies', icon: FlaskConical },
  { id: 'replay', label: 'Replay', icon: History },
  { id: 'market', label: 'Market', icon: ChartLine },
];

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <span className="type-data tabular-nums text-muted-foreground">
      {now.toISOString().slice(11, 16)} UTC
    </span>
  );
}

/**
 * The one shell: product mark, six destinations, the dataset disclosure and
 * theme toggle on the right; the disclaimer and ticker tape along the bottom.
 * Both old surfaces' chrome is absorbed here — there is no second header.
 */
export function AppShell() {
  const route = useRoute();
  const { instruments, quotes, error } = useWatchlist();
  // Rendered once, in one place or the other. See useMediaQuery: two
  // copies hidden by CSS would be two nodes in the accessibility tree.
  // The full header row where it fits, the hamburger wherever it does not:
  // measured, not a breakpoint (see useRowFits).
  const { rowRef, fits: isDesktop } = useRowFits(useIsDesktop());

  // Legacy hashes (`#/`, `#/lab`, anything unknown) are rewritten to the
  // canonical destination hash, without adding a history entry.
  useEffect(() => {
    if (!route.canonical) replaceRoute(route.destination, route.params);
  }, [route]);

  // Backtests run in the background; the Strategies tab says how many are
  // queued or running, wherever you are.
  const activeRuns = useOptionalRuns()?.activeCount ?? 0;

  const [searchOpen, setSearchOpen] = useState(false);
  useCommandPaletteShortcut(useCallback(() => setSearchOpen((current) => !current), []));

  return (
    <div className="relative flex h-screen flex-col">
      <GrainOverlay />

      {/* Above the grain, which is the whole point of the grain. */}
      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        <LiveFeedProvider>
          {/* The header is the whole app's width floor, so it is where the
              phone layout is won or lost: at 390px the desktop row measured
              1,190px of content, and every destination inherited that sideways
              scroll. Wherever the full row does not fit -- a phone, a tablet,
              a narrowed browser window -- it is replaced by MobileHeader: the
              brand, the current page and a menu button. The feed and dataset
              disclosures move to the footer rather than being dropped, because
              they are what say whether the numbers are real. */}
          {isDesktop ? null : (
            <MobileHeader items={NAV} current={route.destination} onNavigate={navigate} />
          )}
          {isDesktop ? (
            <header
              ref={rowRef}
              className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2 lg:gap-6 lg:px-4 lg:py-2.5"
            >
              <div className="flex min-w-0 items-center gap-2 lg:gap-6">
                <span className="hidden font-display text-sm tracking-[-0.02em] sm:inline">
                  QuantLab
                </span>

                <nav aria-label="Destinations" className="flex items-center gap-0.5 lg:gap-1">
                  {NAV.map((item) => (
                    <Button
                      key={item.id}
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-current={route.destination === item.id ? 'page' : undefined}
                      // The label is hidden below `lg`, so the name has to come
                      // from here.
                      aria-label={
                        item.id === 'strategies' && activeRuns > 0
                          ? `${item.label}, ${activeRuns} backtest${activeRuns === 1 ? '' : 's'} running or queued`
                          : item.label
                      }
                      title={item.label}
                      onClick={() => navigate(item.id)}
                      className={cn(
                        // 44px of touch target below `lg` -- the floor a finger
                        // hits reliably -- and the 28px desktop row back at `lg`,
                        // where the pointer is a mouse.
                        'h-11 w-11 justify-center px-0 lg:h-7 lg:w-auto lg:justify-start lg:px-2.5',
                        route.destination === item.id
                          ? 'bg-primary/10 text-primary hover:text-primary'
                          : undefined,
                      )}
                    >
                      <item.icon size={20} strokeWidth={1.5} aria-hidden="true" />
                      <span className="hidden lg:inline">{item.label}</span>
                      {item.id === 'strategies' && activeRuns > 0 ? (
                        <span
                          data-testid="nav-active-runs"
                          className="rounded-sm border border-primary/50 px-1 type-micro tabular-nums text-primary"
                        >
                          {activeRuns}
                        </span>
                      ) : null}
                    </Button>
                  ))}
                </nav>
              </div>

              <div className="flex shrink-0 items-center gap-2 lg:gap-4">
                {isDesktop ? (
                  <>
                    <Clock />
                    <DatasetBadge />
                  </>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label="Search companies and pages"
                  title="Search (Ctrl/Cmd+K)"
                  onClick={() => setSearchOpen(true)}
                  className="gap-2 text-muted-foreground"
                >
                  <Search size={16} strokeWidth={1.5} aria-hidden="true" />
                  <span className="hidden xl:inline">Search</span>
                  <kbd className="hidden type-micro text-muted-foreground xl:inline">⌘K</kbd>
                </Button>
                <GlossaryButton />
                <ThemeToggle />
                <UserMenu />
              </div>
            </header>
          ) : null}

          <DataSourceBanner />

          {/* One destination mounted at a time. This was previously a
              comment about Dockview corrupting its layout when measured at
              0x0; that constraint left with the dock (docs/RESEARCH.md §1d),
              and nothing here needs to be kept alive off-screen any more. */}
          {route.destination === 'overview' ? (
            <OverviewView />
          ) : route.destination === 'research' ? (
            <div className="min-h-0 flex-1">
              <ResearchPage />
            </div>
          ) : route.destination === 'strategies' ? (
            <StrategyLabView instruments={instruments} />
          ) : route.destination === 'replay' ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <ReplayView />
            </div>
          ) : (
            <MarketView
              instruments={instruments}
              feedError={error}
              defaultSymbol={FEATURED_SYMBOLS[0]}
            />
          )}

          <RunNotices />
          <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} destinations={NAV} />

          <footer className="shrink-0">
            <TickerTape quotes={quotes} />
            {/* Where the header's disclosures go on a phone. They are not
                decoration: `sim` and the dataset badge are the difference
                between a demo number and a traded one, so they stay on screen
                at every width -- just at the bottom, where the header has no
                room. Hidden at `lg`, where they are back in the header and
                showing them twice would be noise. */}
            {isDesktop ? null : (
              <div className="flex items-center justify-center gap-3 border-t border-border px-3 py-1.5">
                <DatasetBadge />
              </div>
            )}
          </footer>
        </LiveFeedProvider>
      </div>
    </div>
  );
}
