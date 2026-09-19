import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { ApiError, getHealth, type Health } from './client';

export type DatasetState =
  | { status: 'loading' }
  | { status: 'ready'; health: Health }
  | { status: 'unreachable'; message: string };

const DatasetContext = createContext<DatasetState | null>(null);

function useHealthFetch(skip = false): DatasetState {
  const [state, setState] = useState<DatasetState>({ status: 'loading' });

  useEffect(() => {
    if (skip) return;
    let cancelled = false;
    getHealth()
      .then((health) => {
        if (!cancelled) setState({ status: 'ready', health });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          status: 'unreachable',
          message: error instanceof ApiError ? error.message : 'backend unreachable',
        });
      });
    return () => {
      cancelled = true;
    };
  }, [skip]);

  return state;
}

/**
 * One health read, shared by everything that needs to say which dataset is
 * answering.
 *
 * It exists because the badge and the footer disclaimer were free to disagree:
 * the badge read the backend while the footer asserted "synthetic and
 * fictitious" unconditionally, so a warehouse-backed page claimed both at once.
 * Reading one value in one place is what stops that recurring.
 */
export function DatasetProvider({ children }: { children: ReactNode }) {
  const state = useHealthFetch();
  return <DatasetContext.Provider value={state}>{children}</DatasetContext.Provider>;
}

export function useDataset(): DatasetState {
  const shared = useContext(DatasetContext);
  // A consumer rendered without a provider still has to work -- that is the
  // component in isolation, and its own tests. Both hooks are called
  // unconditionally; the fetch is skipped when a provider already has the answer.
  const own = useHealthFetch(shared !== null);
  return shared ?? own;
}
