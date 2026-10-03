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
  cancelRun as cancelRunRequest,
  createRun,
  createStrategyRun,
  deleteRun,
  getRun,
  isActiveRun,
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
  type RunV2,
  type StrategyRunRequest,
} from '../api/types';

export type LoadStatus = 'loading' | 'ready' | 'error';

/** How often the run list is refreshed while any run is queued or running. */
export const ACTIVE_POLL_MS = 3000;

/** A run that just finished, failed or was queued -- shown as a toast. */
export interface RunNotice {
  id: string;
  runId: string;
  tone: 'good' | 'bad' | 'idle';
  text: string;
}

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
  allRuns: RunV2[];
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
  /**
   * Queue a strategy backtest and return the queued run, without selecting
   * it: the builder stays where it is so the next variant can be submitted.
   */
  submitStrategyRun: (request: StrategyRunRequest) => Promise<RunV2 | null>;
  /** True while a submission is on its way to the server (seconds, not the run). */
  submitting: boolean;
  /** Stops waiting for a submission; the server-side run is unaffected. */
  cancel: () => void;
  /** Cancel a queued run, or ask a running one to stop. */
  cancelRun: (runId: string) => Promise<void>;
  /** Queued + running runs: what the Strategies tab badge counts. */
  activeCount: number;
  /** Toasts for runs that finished or failed while the app was open. */
  notices: RunNotice[];
  dismissNotice: (id: string) => void;
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

  const [allRuns, setAllRuns] = useState<RunV2[]>([]);
  const [runsStatus, setRunsStatus] = useState<LoadStatus>('loading');
  const [runsNonce, setRunsNonce] = useState(0);

  const [sessionRuns, setSessionRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<RunDetailV2 | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [notices, setNotices] = useState<RunNotice[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  // Last seen status per run, to notice queued/running -> finished.
  const lastStatus = useRef<Map<string, string>>(new Map());

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

  const notify = useCallback((notice: Omit<RunNotice, 'id'>) => {
    setNotices((current) => [
      ...current.slice(-3),
      { ...notice, id: `${notice.runId}:${Date.now()}:${Math.random()}` },
    ]);
  }, []);
  const dismissNotice = useCallback(
    (id: string) => setNotices((current) => current.filter((notice) => notice.id !== id)),
    [],
  );

  const activeIds = useMemo(
    () =>
      [...allRuns, ...(activeRun ? [activeRun] : [])]
        // Queued and running runs, and older completed runs whose results the
        // worker is still computing: either way the list has news coming.
        .filter(
          (run) =>
            isActiveRun(run) || (run.status === 'completed' && !run.metrics && !run.results_error),
        )
        .map((run) => run.id)
        .sort()
        .join(','),
    [allRuns, activeRun],
  );

  // While anything is queued or running, refresh the list on a timer and
  // announce each run that finishes. Nothing streams: the worker writes a
  // run's result once, and this picks it up within a few seconds.
  useEffect(() => {
    if (!activeIds) return undefined;
    let cancelled = false;
    const timer = window.setInterval(() => {
      listRuns()
        .then((result) => {
          if (cancelled) return;
          setAllRuns([...result.items].sort(byRecency));
        })
        .catch(() => {
          // A missed poll is retried on the next tick; the list stays as it was.
        });
    }, ACTIVE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeIds]);

  useEffect(() => {
    const seen = lastStatus.current;
    for (const run of allRuns) {
      const before = seen.get(run.id);
      seen.set(run.id, run.status);
      if (!before || before === run.status) continue;
      if (before !== 'queued' && before !== 'running') continue;
      const label = run.name ?? run.strategy?.name ?? run.model_name;
      if (run.status === 'completed') {
        notify({
          runId: run.id,
          tone: 'good',
          text: `Backtest "${label}" finished — ${run.signal_count} signal${run.signal_count === 1 ? '' : 's'}.`,
        });
      } else if (run.status === 'failed') {
        notify({ runId: run.id, tone: 'bad', text: `Backtest "${label}" failed: ${run.error ?? 'no reason given'}` });
      }
      // The run being inspected finished: load its signals and results.
      if (activeRun?.id === run.id) {
        getRun(run.id)
          .then(setActiveRun)
          .catch(() => undefined);
      }
    }
  }, [allRuns, activeRun?.id, notify]);

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
      setAllRuns((current) => [run as RunV2, ...current]);
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

  const submitStrategyRun = useCallback(
    async (request: StrategyRunRequest): Promise<RunV2 | null> => {
      const controller = new AbortController();
      abortRef.current = controller;
      setSubmitting(true);
      setRunError(null);
      try {
        const run = await createStrategyRun(request, controller.signal);
        lastStatus.current.set(run.id, run.status);
        setAllRuns((current) => [run, ...current.filter((existing) => existing.id !== run.id)]);
        return run;
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === 'AbortError') return null;
        setRunError(caught instanceof ApiError ? caught.message : 'the run could not be submitted');
        return null;
      } finally {
        abortRef.current = null;
        setSubmitting(false);
      }
    },
    [],
  );

  const cancelRun = useCallback(async (runId: string) => {
    const run = await cancelRunRequest(runId);
    lastStatus.current.set(run.id, run.status);
    setAllRuns((current) => current.map((existing) => (existing.id === runId ? run : existing)));
    setActiveRun((current) => (current?.id === runId ? { ...current, ...run } : current));
  }, []);

  // Aborts the client's wait. The server finishes the computation it started —
  // at this data scale that costs milliseconds, and the UI must not claim
  // otherwise.
  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setInFlight(false);
    setSubmitting(false);
  }, []);

  const clearActiveRun = useCallback(() => setActiveRun(null), []);

  const save = useCallback(async (runId: string, name: string) => {
    const saved = await saveRun(runId, name);
    setAllRuns((current) => current.map((run) => (run.id === runId ? (saved as RunV2) : run)));
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

  const activeCount = useMemo(() => allRuns.filter(isActiveRun).length, [allRuns]);

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
    submitStrategyRun,
    submitting,
    cancel,
    cancelRun,
    activeCount,
    notices,
    dismissNotice,
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

/** The store where there is one, null where there is not (isolated renders). */
export function useOptionalRuns(): RunsContextValue | null {
  return useContext(RunsContext) ?? null;
}
