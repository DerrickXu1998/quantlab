import { Workspace, type WorkspaceHandle } from '../workspace/Workspace';
import { WorkbenchProvider } from '../workbench/WorkbenchContext';
import { WorkspaceProvider } from '../workspace/WorkspaceContext';

export function SignalsPage({ onReady }: { onReady?: (handle: WorkspaceHandle) => void } = {}) {
  return (
    <WorkspaceProvider>
      <WorkbenchProvider>
        <div className="signals-page h-full">
          <Workspace onReady={onReady} />
        </div>
      </WorkbenchProvider>
    </WorkspaceProvider>
  );
}
