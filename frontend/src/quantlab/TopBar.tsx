import { Activity, ArrowLeft, CircleDot } from 'lucide-react';
import { useEffect, useState } from 'react';
import { StatusBadge } from './chrome/StatusBadge';
import { useFeedStatus } from './feed/FeedProvider';

export type LabView = 'overview' | 'strategy';

const VIEWS: { id: LabView; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'strategy', label: 'Strategy Lab' },
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

export function TopBar({
  view,
  onView,
  onExit,
}: {
  view: LabView;
  onView: (next: LabView) => void;
  onExit: () => void;
}) {
  const status = useFeedStatus();

  return (
    <header className="flex shrink-0 items-center justify-between gap-6 border-b border-border px-4 py-2.5">
      <div className="flex items-center gap-6">
        <button
          type="button"
          onClick={onExit}
          title="Back to the Signal Viewer"
          className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={16} strokeWidth={1.5} />
          Signal Viewer
        </button>

        <span className="font-display text-sm tracking-[-0.02em]">Quant Lab</span>

        <nav className="flex items-center gap-1">
          {VIEWS.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-current={view === item.id ? 'page' : undefined}
              onClick={() => onView(item.id)}
              className={`rounded-sm px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors ${
                view === item.id
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="flex items-center gap-4">
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
          <span className="font-mono uppercase tracking-wider">{status}</span>
          <StatusBadge tone="idle">sim</StatusBadge>
        </span>
        <Clock />
      </div>
    </header>
  );
}
