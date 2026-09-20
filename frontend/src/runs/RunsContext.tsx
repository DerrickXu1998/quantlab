import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  ApiError,
  createRun,
  createStrategyRun,
  deleteRun,
  getRun,
  listModels,
  listRuns,
  saveRun,
  type Run,
  type RunRequest,
} from '../api/client';
import {
  asCatalogModel,
  type CatalogModel,
  type RawCatalogModel,
  type RunDetailV2,
  type StrategyRunRequest,
} from '../api/types';

export type LoadStatus = 'loading' | 'ready' | 'error';

/** A registered model joined to its run history, newest first. */
export interface ModelEntry {
  model: RawCatalogModel;
  runs: Run[];
  latest: Run | null;
}

export interface RunsContextValue {
  // The model registry.
  models: RawCatalogModel[];
  /** The same registry with the contract-v2 fields normalised (§2). */
  catalog: CatalogModel[];
  modelsStatus: LoadStatus;
  selectedModel: RawCatalogModel | null;
  selectModel: (model: RawCatalogModel | null) => void;
  /** Models joined with their run history (the old useStrategies join). */
  modelEntries: ModelEntry[];

  // The run history, from the backend.
  allRuns: Run[];
  runsStatus: LoadStatus;
  reloadRuns: () => void;

  // Session state: runs started here, and the one being inspected.
  sessionRuns: Run[];
  activeRun: RunDetailV2 | null;
  inFlight: boolean;
  runError: string | null;
  start: (request: RunRequest) => Promise<void>;
  /** The same run machinery, given a composed strategy instead of one model. */
  startStrategyRun: (request: StrategyRunRequest) => Promise<void>;
  cancel: () => void;
  select: (runId: string) => Promise<void>;
  clearActiveRun: () => void;

  // The previously dead ends: naming a run keeps it, deleting removes it.
  save: (runId: string, name: string) => Promise<void>;
  remove: (runId: string) => Promise<void>;

  /** Most recent completed run — what Overview falls back to when nothing is selected. */
  latestCompleted: Run | null;
}

const RunsContext = createContext<RunsContextValue | undefined>(undefined);

function byRecency(a: Run, b: Run): number {
  return b.created_at.localeCompare(a.created_at);
}

/**
 * The one runs store, above every destination.
 *
 * It merges what used to be three separate holders — the workbench's session
 * runs, the Strategy Lab's local run state, and Overview's latest-run fetch —
 * so a run created in Research is already selected when the researcher walks
 * over to Strategies, and a saved run is the same object everywhere.
 */
export function RunsProvider({ children }: { children: ReactNode }) {
  const [models, setModels] = useState<RawCatalogModel[]>([]);
  const [modelsStatus, setModelsStatus] = useState<LoadStatus>('loading');
  const [selectedModel, setSelectedModel] = useState<RawCatalogModel | null>(null);

  const [allRuns, setAllRuns] = useState<Run[]>([]);
  const [runsStatus, setRunsStatus] = useState<LoadStatus>('loading');
  const [runsNonce, setRunsNonce] = useState(0);

  const [sessionRuns, setSessionRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<RunDetailV2 | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    listModels()
      .then((result) => {
        if (cancelled) return;
        setModels(result.items);
        setModelsStatus('ready');
        // Select the first model so the configuration form is immediately
        // usable, without hardcoding which model that is.
        setSelectedModel((current) => current ?? result.items[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setModelsStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setRunsStatus('loading');
    listRuns()
      .then((result) => {
        if (cancelled) return;
        setAllRuns([...result.items].sort(byRecency));
        setRunsStatus('ready');
      })
      .catch(() => {
        if (!cancelled) setRunsStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [runsNonce]);

  const reloadRuns = useCallback(() => setRunsNonce((n) => n + 1), []);

  const select = useCallback(async (runId: string) => {
    try {
      setActiveRun(await getRun(runId));
    } catch (error: unknown) {
      setRunError(error instanceof Error ? error.message : 'could not load the run');
    }
  }, []);

  // One body for both request shapes: §5 promotes a legacy single-model
  // request to a one-component strategy server-side, so there is one execution
  // path there and there is one here too.
  const runWith = useCallback(async (submit: (signal: AbortSignal) => Promise<Run>) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setInFlight(true);
    setRunError(null);
    try {
      const run = await submit(controller.signal);
      // A new run never replaces an earlier one (FR-012).
      setSessionRuns((current) => [run, ...current]);
      setAllRuns((current) => [run, ...current]);
      setActiveRun(await getRun(run.id));
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return;
      setRunError(caught instanceof ApiError ? caught.message : 'the run could not be started');
    } finally {
      abortRef.current = null;
      setInFlight(false);
    }
  }, []);

  const start = useCallback(
    (request: RunRequest) => runWith((signal) => createRun(request, signal)),
    [runWith],
  );

  const startStrategyRun = useCallback(
    (request: StrategyRunRequest) => runWith((signal) => createStrategyRun(request, signal)),
    [runWith],
  );

  // Aborts the client's wait. The server finishes the computation it started —
  // at this data scale that costs milliseconds, and the UI must not claim
  // otherwise.
  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setInFlight(false);
  }, []);

  const clearActiveRun = useCallback(() => setActiveRun(null), []);

  const save = useCallback(async (runId: string, name: string) => {
    const saved = await saveRun(runId, name);
    setAllRuns((current) => current.map((run) => (run.id === runId ? saved : run)));
    setSessionRuns((current) => current.map((run) => (run.id === runId ? saved : run)));
    setActiveRun((current) => (current?.id === runId ? { ...current, name: saved.name } : current));
  }, []);

  const remove = useCallback(async (runId: string) => {
    await deleteRun(runId);
    setAllRuns((current) => current.filter((run) => run.id !== runId));
    setSessionRuns((current) => current.filter((run) => run.id !== runId));
    setActiveRun((current) => (current?.id === runId ? null : current));
  }, []);

  const modelEntries = useMemo<ModelEntry[]>(
    () =>
      models.map((model) => {
        const own = allRuns.filter((run) => run.model_name === model.name).sort(byRecency);
        return { model, runs: own, latest: own[0] ?? null };
      }),
    [models, allRuns],
  );

  const catalog = useMemo<CatalogModel[]>(() => models.map(asCatalogModel), [models]);

  const latestCompleted = useMemo(
    () => allRuns.filter((run) => run.status === 'completed').sort(byRecency)[0] ?? null,
    [allRuns],
  );

  const value: RunsContextValue = {
    models,
    catalog,
    modelsStatus,
    selectedModel,
    selectModel: setSelectedModel,
    modelEntries,
    allRuns,
    runsStatus,
    reloadRuns,
    sessionRuns,
    activeRun,
    inFlight,
    runError,
    start,
    startStrategyRun,
    cancel,
    select,
    clearActiveRun,
    save,
    remove,
    latestCompleted,
  };

  return <RunsContext.Provider value={value}>{children}</RunsContext.Provider>;
}

export function useRuns(): RunsContextValue {
  const ctx = useContext(RunsContext);
  if (!ctx) {
    throw new Error('useRuns must be used within a RunsProvider');
  }
  return ctx;
}
