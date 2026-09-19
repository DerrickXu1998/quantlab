import { useRef, useState } from 'react';
import { DataDisclaimer } from '../components/DataDisclaimer';
import { Button } from '../components/ui/button';
import { SignalsPage } from '../pages/SignalsPage';
import { ThemeToggle } from '../theme/ThemeToggle';
import { DatasetBadge } from '../workbench/DatasetBadge';
import type { WorkspaceHandle } from '../workspace/Workspace';

/**
 * The docking Signal Viewer: the original surface, lifted out of App so a
 * second one can sit beside it. Nothing inside it changed.
 */
export function SignalsSurface({ onOpenLab }: { onOpenLab: () => void }) {
  const workspace = useRef<WorkspaceHandle | null>(null);
  const [ready, setReady] = useState(false);

  return (
    // h-screen + min-h-0 below: docking needs a bounded, full-height container.
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="shrink-0 border-b border-border bg-card">
        <div className="flex items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold tracking-tight">QuantLab Signal Viewer</span>
            <DatasetBadge />
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onOpenLab}>
              Open Quant Lab
            </Button>
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
        <DataDisclaimer />
      </footer>
    </div>
  );
}
