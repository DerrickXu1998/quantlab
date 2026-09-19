import { useRef, useState } from 'react';
import { SignalsPage } from './pages/SignalsPage';
import { SplashScreen } from './splash/SplashScreen';
import { ThemeToggle } from './theme/ThemeToggle';
import { DatasetBadge } from './workbench/DatasetBadge';
import { Button } from './components/ui/button';
import type { WorkspaceHandle } from './workspace/Workspace';

export default function App() {
  const workspace = useRef<WorkspaceHandle | null>(null);
  const [ready, setReady] = useState(false);
  const [booting, setBooting] = useState(true);

  return (
    // h-screen + min-h-0 below: docking needs a bounded, full-height container.
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* Rendered over the workspace rather than instead of it, so the page
          is already loaded and behind the field as it contracts away. */}
      {booting && <SplashScreen onComplete={() => setBooting(false)} />}

      <header className="shrink-0 border-b border-border bg-card">
        <div className="flex items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold tracking-tight">QuantLab Signal Viewer</span>
            <DatasetBadge />
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!ready}
              onClick={() => workspace.current?.resetLayout()}
            >
              Reset layout
            </Button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1">
        <SignalsPage
          onReady={(handle) => {
            workspace.current = handle;
            setReady(true);
          }}
        />
      </main>

      <footer className="shrink-0 px-6 py-2 text-center text-xs text-muted-foreground">
        All instruments, prices, and signals shown here are synthetic and fictitious — demo data
        only, not real market data.
      </footer>
    </div>
  );
}
