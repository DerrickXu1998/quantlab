import { useEffect, useState } from 'react';
import { getRunPerformance, type RunPerformance } from '../../api/client';

export type PerformanceState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; performance: RunPerformance }
  | { status: 'error'; message: string };

/**
 * Equity curve, benchmark, trades and risk metrics for one run.
 *
 * All of it computed by the backend: the frontend must not embed analytical
 * computation (Constitution V), so this hook fetches and renders, and derives
 * nothing.
 */
export function useRunPerformance(runId: string | null): PerformanceState {
  const [state, setState] = useState<PerformanceState>({ status: 'idle' });

  useEffect(() => {
    if (!runId) {
      setState({ status: 'idle' });
      return;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    getRunPerformance(runId)
      .then((performance) => {
        if (!cancelled) setState({ status: 'ready', performance });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : 'could not load performance',
        });
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return state;
}
