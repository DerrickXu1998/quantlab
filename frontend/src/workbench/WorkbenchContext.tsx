import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { listModels, type Model } from '../api/client';
import { useRuns, type RunsState } from './useRuns';

interface WorkbenchContextValue {
  models: Model[];
  modelsStatus: 'loading' | 'ready' | 'error';
  selected: Model | null;
  setSelected: (model: Model) => void;
  runs: RunsState;
}

const WorkbenchContext = createContext<WorkbenchContextValue | undefined>(undefined);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [models, setModels] = useState<Model[]>([]);
  const [modelsStatus, setModelsStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [selected, setSelected] = useState<Model | null>(null);
  const runs = useRuns();

  useEffect(() => {
    let cancelled = false;
    listModels()
      .then((result) => {
        if (cancelled) return;
        setModels(result.items);
        setModelsStatus('ready');
        // Select the first model so the configuration panel is immediately
        // usable, without hardcoding which model that is.
        setSelected((current) => current ?? result.items[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setModelsStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <WorkbenchContext.Provider value={{ models, modelsStatus, selected, setSelected, runs }}>
      {children}
    </WorkbenchContext.Provider>
  );
}

export function useWorkbench(): WorkbenchContextValue {
  const ctx = useContext(WorkbenchContext);
  if (!ctx) {
    throw new Error('useWorkbench must be used within a WorkbenchProvider');
  }
  return ctx;
}
