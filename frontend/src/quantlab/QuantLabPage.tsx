import { useState } from 'react';
import { GrainOverlay } from './chrome/GrainOverlay';
import { useWatchlist } from './data/useWatchlist';
import { FeedProvider } from './feed/FeedProvider';
import { TickerTape } from './panels/TickerTape';
import { TopBar, type LabView } from './TopBar';
import { OverviewView } from './views/OverviewView';
import { StrategyLabView } from './views/StrategyLabView';

/**
 * The Quant Lab surface.
 *
 * `.quantlab` scopes the terminal palette to this subtree by redefining the
 * same design tokens the rest of the app uses. Nothing touches <html>, so the
 * Signal Viewer's light/dark toggle is unaffected and every shared ui/*
 * primitive re-skins here for free.
 *
 * What is real and what is not: strategies, runs, coverage, trades, the equity
 * curve and every risk metric come from the backend. The per-second price
 * movement does not — QuantLab stores end-of-day bars and has no streaming
 * endpoint, so the feed is a walk seeded from real last closes, and the panels
 * that show it are tagged.
 */
export function QuantLabPage({ onExit }: { onExit: () => void }) {
  const [view, setView] = useState<LabView>('overview');
  const [selected, setSelected] = useState<string | null>(null);
  const { instruments, seeds, error } = useWatchlist();

  return (
    <div className="quantlab relative flex h-screen flex-col">
      <GrainOverlay />

      {/* Above the grain, which is the whole point of the grain. */}
      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        <FeedProvider seeds={seeds}>
          <TopBar view={view} onView={setView} onExit={onExit} />

          {view === 'overview' ? (
            <OverviewView
              instruments={instruments}
              feedError={error}
              selected={selected}
              onSelect={setSelected}
              onOpenStrategyLab={() => setView('strategy')}
            />
          ) : (
            <StrategyLabView instruments={instruments} />
          )}

          <TickerTape />
        </FeedProvider>
      </div>
    </div>
  );
}
