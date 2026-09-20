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
import { DataDisclaimer } from '../components/DataDisclaimer';
import { Button } from '../components/ui/button';
import { StatusBadge } from '../components/ui/status-badge';
import { SignalsPage } from '../pages/SignalsPage';
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
import { navigate, replaceRoute, useRoute, type Destination } from './router';

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
          <header className="flex shrink-0 items-center justify-between gap-6 border-b border-border px-4 py-2.5">
            <div className="flex items-center gap-6">
              <span className="font-display text-sm tracking-[-0.02em]">QuantLab</span>

              <nav aria-label="Destinations" className="flex items-center gap-1">
                {NAV.map((item) => (
                  <Button
                    key={item.id}
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-current={route.destination === item.id ? 'page' : undefined}
                    onClick={() => navigate(item.id)}
                    className={
                      route.destination === item.id
                        ? 'bg-primary/10 text-primary hover:text-primary'
                        : undefined
                    }
                  >
                    <item.icon size={20} strokeWidth={1.5} aria-hidden="true" />
                    {item.label}
                    {item.simulated ? (
                      <StatusBadge tone="simulated" title={item.simulated}>
                        sim
                      </StatusBadge>
                    ) : null}
                  </Button>
                ))}
              </nav>
            </div>

            <div className="flex items-center gap-4">
              <FeedStatus />
              <Clock />
              <DatasetBadge />
              <ThemeToggle />
            </div>
          </header>

          {/* Conditional, never `hidden`: a display:none Dockview measures 0x0
              and corrupts its layout. layoutStorage restores it on return. */}
          {route.destination === 'overview' ? (
            <OverviewView />
          ) : route.destination === 'research' ? (
            <div className="min-h-0 flex-1">
              <SignalsPage />
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
            <div className="border-t border-border px-4 py-1.5 text-center text-[11px] text-muted-foreground">
              <DataDisclaimer />
            </div>
          </footer>
        </FeedProvider>
      </div>
    </div>
  );
}
