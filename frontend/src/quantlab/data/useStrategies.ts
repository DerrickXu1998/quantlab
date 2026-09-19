import { useCallback, useEffect, useState } from 'react';
import { listModels, listRuns, type Model, type Run } from '../../api/client';

export interface Strategy {
  model: Model;
  /** Every run recorded against this model, newest first. */
  runs: Run[];
  latest: Run | null;
}

export type StrategiesState =
  | { status: 'loading' }
  | { status: 'ready'; strategies: Strategy[] }
  | { status: 'error'; message: string };

/**
 * The strategy list, entirely from the backend registry.
 *
 * A "strategy" here is a registered model joined to its run history. Nothing
 * about the list is hardcoded — a model added to the registry shows up without
 * a frontend change (Constitution II).
 */
export function useStrategies(): StrategiesState & { reload: () => void } {
  const [state, setState] = useState<StrategiesState>({ status: 'loading' });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listModels(), listRuns()])
      .then(([models, runs]) => {
        if (cancelled) return;
        const strategies = models.items.map((model) => {
          const own = runs.items.filter((run) => run.model_name === model.name);
          own.sort((a, b) => b.created_at.localeCompare(a.created_at));
          return { model, runs: own, latest: own[0] ?? null };
        });
        setState({ status: 'ready', strategies });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : 'could not load strategies',
        });
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
