import {
  Activity,
  ArrowLeftRight,
  ChartLine,
  CircleDot,
  FlaskConical,
  History,
  LayoutDashboard,
  Search,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { UserMenu } from '../auth/UserMenu';
import { DataDisclaimer } from '../components/DataDisclaimer';
import { Button } from '../components/ui/button';
import { StatusBadge } from '../components/ui/status-badge';
import { ResearchPage } from '../pages/ResearchPage';
import { GrainOverlay } from '../quantlab/chrome/GrainOverlay';
import { useWatchlist } from '../quantlab/data/useWatchlist';
import { FeedProvider, useFeedStatus } from '../quantlab/feed/FeedProvider';
import { TickerTape } from '../quantlab/panels/TickerTape';
import { ExecutionView } from '../quantlab/views/ExecutionView';
import { IndicatorsView } from '../quantlab/views/IndicatorsView';
import { OverviewView } from '../quantlab/views/OverviewView';
import { ReplayView } from '../quantlab/views/ReplayView';
import { StrategyLabView } from '../quantlab/views/StrategyLabView';
import { ThemeToggle } from '../theme/ThemeToggle';
import { DatasetBadge } from '../workbench/DatasetBadge';
import { cn } from '../lib/utils';
import { navigate, replaceRoute, useRoute, type Destination } from './router';
import { useIsDesktop } from './useMediaQuery';

const NAV: { id: Destination; label: string; icon: LucideIcon; simulated?: string }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'research', label: 'Research', icon: Search },
  { id: 'strategies', label: 'Strategies', icon: FlaskConical },
  { id: 'replay', label: 'Replay', icon: History },
  { id: 'market', label: 'Market', icon: ChartLine },
  {
    id: 'execution',
    label: 'Execution',
    icon: ArrowLeftRight,
    // The one destination that is entirely a simulation — marked on the nav
    // item itself, not only on its panels.
    simulated: 'There is no execution backend; everything in Execution is simulated.',
  },
];

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
      {now.toISOString().slice(11, 19)} UTC
    </span>
  );
}

function FeedStatus() {
  const status = useFeedStatus();
  return (
    <span
      data-testid="feed-status"
      className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
      title="Simulated market data — QuantLab has no streaming feed"
    >
      {status === 'live' ? (
        <CircleDot size={16} strokeWidth={1.5} className="text-primary" />
      ) : (
        <Activity size={16} strokeWidth={1.5} />
      )}
      <span className="font-mono uppercase tracking-[0.12em]">{status}</span>
      <StatusBadge tone="simulated">sim</StatusBadge>
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
  const { instruments, seeds, error } = useWatchlist();
  // Rendered once, in one place or the other. See useMediaQuery: two
  // copies hidden by CSS would be two nodes in the accessibility tree.
  const isDesktop = useIsDesktop();

  // Legacy hashes (`#/`, `#/lab`, anything unknown) are rewritten to the
  // canonical destination hash, without adding a history entry.
  useEffect(() => {
    if (!route.canonical) replaceRoute(route.destination, route.params);
  }, [route]);

  return (
    <div className="relative flex h-screen flex-col">
      <GrainOverlay />

      {/* Above the grain, which is the whole point of the grain. */}
      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        <FeedProvider seeds={seeds}>
          {/* The header is the whole app's width floor, so it is where the
              phone layout is won or lost: at 390px the desktop row measured
              1,190px of content, and every destination inherited that sideways
              scroll.

              Three things give way, in order of how little they cost: the
              destination labels (the icon and an aria-label carry the name),
              the clock (a phone has one), and the feed and dataset disclosures
              -- moved to the footer on small screens rather than dropped,
              because they are what say whether the numbers are real. Above
              `lg` every one of them returns and the row is what it was. */}
          <header className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2 lg:gap-6 lg:px-4 lg:py-2.5">
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
                    // from here. It carries the simulated marker too: an
                    // aria-label overrides the element's contents, and without
                    // this the `sim` badge would drop out of the accessible
                    // name that previously included it.
                    aria-label={item.simulated ? `${item.label} (simulated)` : item.label}
                    title={item.simulated ?? item.label}
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
                    {item.simulated ? (
                      <StatusBadge
                        tone="simulated"
                        title={item.simulated}
                        className="hidden lg:inline-flex"
                      >
                        sim
                      </StatusBadge>
                    ) : null}
                  </Button>
                ))}
              </nav>
            </div>

            <div className="flex shrink-0 items-center gap-2 lg:gap-4">
              {isDesktop ? (
                <>
                  <FeedStatus />
                  <Clock />
                  <DatasetBadge />
                </>
              ) : null}
              <ThemeToggle />
              <UserMenu />
            </div>
          </header>

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
          ) : route.destination === 'market' ? (
            <IndicatorsView instruments={instruments} feedError={error} />
          ) : (
            <ExecutionView instruments={instruments} feedError={error} />
          )}

          <footer className="shrink-0">
            <TickerTape />
            {/* Where the header's disclosures go on a phone. They are not
                decoration: `sim` and the dataset badge are the difference
                between a demo number and a traded one, so they stay on screen
                at every width -- just at the bottom, where the header has no
                room. Hidden at `lg`, where they are back in the header and
                showing them twice would be noise. */}
            {isDesktop ? null : (
              <div className="flex items-center justify-center gap-3 border-t border-border px-3 py-1.5">
                <FeedStatus />
                <DatasetBadge />
              </div>
            )}
            <div className="border-t border-border px-4 py-1.5 text-center text-[11px] text-muted-foreground">
              <DataDisclaimer />
            </div>
          </footer>
        </FeedProvider>
      </div>
    </div>
  );
}
