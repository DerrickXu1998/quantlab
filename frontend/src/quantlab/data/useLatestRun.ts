import { useEffect, useState } from 'react';
import { getRun, listRuns, type RunDetail } from '../../api/client';

export type LatestRunState =
  | { status: 'loading' }
  | { status: 'empty' }
  | { status: 'ready'; run: RunDetail }
  | { status: 'error'; message: string };

/**
 * The most recent completed run, which is what Overview reports on.
 *
 * There is no portfolio in QuantLab — no execution, no account, no positions
 * of its own. The nearest real thing is the last experiment a researcher
 * actually ran, so Overview shows that rather than inventing a book.
 */
export function useLatestRun(nonce = 0): LatestRunState {
  const [state, setState] = useState<LatestRunState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });

    listRuns()
      .then(async (list) => {
        const completed = list.items
          .filter((run) => run.status === 'completed')
          .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
        if (!completed) {
          if (!cancelled) setState({ status: 'empty' });
          return;
        }
        const detail = await getRun(completed.id);
        if (!cancelled) setState({ status: 'ready', run: detail });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : 'could not reach the backend',
        });
      });

    return () => {
      cancelled = true;
    };
  }, [nonce]);

  return state;
}
