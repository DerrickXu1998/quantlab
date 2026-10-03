import { useEffect, useState } from 'react';
import { ApiError, getRunPerformance } from '../../api/client';
import type { RunPerformanceV2 } from '../../api/types';

export type PerformanceState =
  | { status: 'idle' }
  | { status: 'loading' }
  /** An older run whose stored results the worker has not computed yet. */
  | { status: 'pending' }
  | { status: 'ready'; performance: RunPerformanceV2 }
  | { status: 'error'; message: string };

/** How often to ask again while an older run's results are being prepared. */
export const PENDING_RETRY_MS = 5000;

/**
 * Equity curve, benchmark, trades and risk metrics for one run.
 *
 * All of it computed by the backend, once, and stored with the run: this hook
 * reads it and derives nothing (Constitution V). A run recorded before results
 * were stored answers 409 until the worker has computed them; that is a
 * "being prepared" state, asked again every few seconds, not an error.
 */
export function useRunPerformance(runId: string | null): PerformanceState {
  const [state, setState] = useState<PerformanceState>({ status: 'idle' });

  useEffect(() => {
    if (!runId) {
      setState({ status: 'idle' });
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    setState({ status: 'loading' });
    const load = () => {
      getRunPerformance(runId)
        .then((performance) => {
          if (!cancelled) setState({ status: 'ready', performance });
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          if (error instanceof ApiError && error.status === 409) {
            setState({ status: 'pending' });
            timer = window.setTimeout(load, PENDING_RETRY_MS);
            return;
          }
          setState({
            status: 'error',
            message: error instanceof Error ? error.message : 'could not load performance',
          });
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId]);

  return state;
}
