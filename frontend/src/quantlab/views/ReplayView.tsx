import { ServerCrash } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { useRuns } from '../../runs/RunsContext';
import { EmptyState } from '../chrome/EmptyState';
import { ReplayPanel } from '../panels/ReplayPanel';

/**
 * Replay: a completed run's history, streamed back day by day. The panel gets
 * the run list from the shared store — the same runs Research and Strategies
 * already show.
 */
export function ReplayView() {
  const { allRuns, runsStatus, reloadRuns } = useRuns();

  if (runsStatus === 'error') {
    return (
      <EmptyState
        testId="replay-runs-error"
        icon={ServerCrash}
        tone="error"
        title="Backend unreachable"
        detail="The run history could not be loaded."
        action={
          <Button type="button" variant="outline" size="sm" onClick={reloadRuns}>
            Retry
          </Button>
        }
      />
    );
  }

  return <ReplayPanel runs={allRuns} />;
}
