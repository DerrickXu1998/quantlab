import { useCallback, useRef, useState } from 'react';
import {
  ApiError,
  createRun,
  getRun,
  type Run,
  type RunDetail,
  type RunRequest,
} from '../api/client';

export interface RunsState {
  runs: Run[];
  activeRun: RunDetail | null;
  inFlight: boolean;
  error: string | null;
  start: (request: RunRequest) => Promise<void>;
  cancel: () => void;
  select: (runId: string) => Promise<void>;
}

export function useRuns(): RunsState {
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<RunDetail | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const select = useCallback(async (runId: string) => {
    setActiveRun(await getRun(runId));
  }, []);

  const start = useCallback(async (request: RunRequest) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setInFlight(true);
    setError(null);
    try {
      const run = await createRun(request, controller.signal);
      // A new run never replaces an earlier one (FR-012).
      setRuns((current) => [run, ...current]);
      setActiveRun(await getRun(run.id));
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return;
      setError(caught instanceof ApiError ? caught.message : 'the run could not be started');
    } finally {
      abortRef.current = null;
      setInFlight(false);
    }
  }, []);

  // Aborts the client's wait. The server finishes the computation it started —
  // at this data scale that costs milliseconds, and the UI must not claim
  // otherwise.
  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setInFlight(false);
  }, []);

  return { runs, activeRun, inFlight, error, start, cancel, select };
}
