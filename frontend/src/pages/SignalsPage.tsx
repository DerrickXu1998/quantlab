import { useRef, useState } from 'react';
import { useRoute } from '../chrome/router';
import { Button } from '../components/ui/button';
import { Workspace, type WorkspaceHandle } from '../workspace/Workspace';
import { WorkspaceProvider } from '../workspace/WorkspaceContext';

/**
 * The Research destination: the dockable signal workspace.
 *
 * The models/runs store is app-level now, so a run started here is already
 * selected when the researcher walks to Strategies. `?instrument=…` on the
 * hash is the Market destination's "Signals for X" handoff.
 */
export function SignalsPage() {
  const route = useRoute();
  const instrument = route.destination === 'research' ? route.params.get('instrument') : null;
  const workspace = useRef<WorkspaceHandle | null>(null);
  const [ready, setReady] = useState(false);

  return (
    <WorkspaceProvider instrumentFilter={instrument}>
      <div className="signals-page h-full">
        <Workspace
          onReady={(handle) => {
            workspace.current = handle;
            setReady(true);
          }}
          actions={
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!ready}
              onClick={() => workspace.current?.resetLayout()}
            >
              Reset layout
            </Button>
          }
        />
      </div>
    </WorkspaceProvider>
  );
}
