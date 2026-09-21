import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, listUniverses, screen } from '../../api/client';
import type { ScreenConstraint, ScreenMetric, ScreenResult } from '../../api/types';

/**
 * The reads Screen mode is built on, in the states they can really be in.
 *
 * Four, not three — the same distinction `strategies/useFundamentals.ts` draws
 * and for the same reason. `/screen` and `/universes` are new routes being
 * written in parallel with this UI, so a 404 is the *expected* answer from a
 * deployment that has not shipped them yet. That is a statement about the
 * backend ("it does not serve this"), which is a different fact from a
 * failure ("it fell over") and a very different fact from an empty result
 * ("nothing in the universe qualified"). Collapsing them would have this
 * screen tell a researcher that no company passed their constraints when in
 * truth nobody ever asked the question.
 */
export type ReadStatus = 'loading' | 'ready' | 'unsupported' | 'error';

function classify(caught: unknown): { status: 'unsupported' | 'error'; message: string } {
  if (caught instanceof ApiError && caught.status === 404) {
    return {
      status: 'unsupported',
      message: 'This backend does not serve the screener.',
    };
  }
  return {
    status: 'error',
    message: caught instanceof ApiError ? caught.message : 'the screener is unreachable',
  };
}

/** One named list a screen may be run over, as `/universes` reports it. */
export interface UniverseSummary {
  name: string;
  as_of: string;
  size: number;
}

export interface UniversesRead {
  universes: UniverseSummary[];
  status: ReadStatus;
  message: string | null;
  reload: () => void;
}

/**
 * The universes on offer.
 *
 * Read once on mount and never re-derived from a screen result: the list of
 * lists is a property of the warehouse, not of the question being asked.
 */
export function useUniverses(): UniversesRead {
  const [universes, setUniverses] = useState<UniverseSummary[]>([]);
  const [status, setStatus] = useState<ReadStatus>('loading');
  const [message, setMessage] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    listUniverses()
      .then((result) => {
        if (cancelled) return;
        setUniverses(result.items);
        setMessage(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const classified = classify(caught);
        setUniverses([]);
        setMessage(
          classified.status === 'unsupported'
            ? 'This backend does not publish universes, so there is nothing to screen within.'
            : classified.message,
        );
        setStatus(classified.status);
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  return { universes, status, message, reload: () => setNonce((value) => value + 1) };
}

/**
 * A screen is an action, so it has an idle state a read does not.
 *
 * `idle` is "you have not asked yet" and it is a real, designed state: the
 * mode opens on it, and it is what stops an empty table from reading as
 * "nothing qualified".
 */
export type ScreenStatus = 'idle' | 'running' | 'ready' | 'unsupported' | 'error';

export interface ScreenQuery {
  universe: string;
  constraints: ScreenConstraint[];
  metrics: ScreenMetric[];
  asOf: string | null;
  sortBy: ScreenMetric | null;
  descending: boolean;
  limit: number;
}

export interface ScreenRun {
  result: ScreenResult | null;
  status: ScreenStatus;
  message: string | null;
  /** The query the result on screen answers — not the one being edited. */
  answered: ScreenQuery | null;
  run: (query: ScreenQuery) => void;
}

/**
 * Run a screen, explicitly.
 *
 * Never fired from a change handler. A screen is ~1s of index scan over a
 * 598-name universe (docs/RESEARCH.md §2), and firing one per keystroke would
 * both hammer the warehouse and paint a sequence of half-answers the user did
 * not ask for. The caller owns a Run affordance; this owns what happens after
 * it is pressed.
 */
export function useScreen(): ScreenRun {
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [status, setStatus] = useState<ScreenStatus>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const [answered, setAnswered] = useState<ScreenQuery | null>(null);
  // Monotonic, so a slow first screen landing after a fast second one cannot
  // overwrite the newer answer with the older one.
  const latest = useRef(0);

  const run = useCallback((query: ScreenQuery) => {
    const ticket = latest.current + 1;
    latest.current = ticket;
    setStatus('running');
    setMessage(null);
    screen({
      universe: query.universe,
      constraints: query.constraints,
      metrics: query.metrics,
      asOf: query.asOf ?? undefined,
      sortBy: query.sortBy ?? undefined,
      descending: query.descending,
      limit: query.limit,
    })
      .then((next) => {
        if (latest.current !== ticket) return;
        setResult(next);
        setAnswered(query);
        setMessage(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (latest.current !== ticket) return;
        const classified = classify(caught);
        setResult(null);
        setAnswered(null);
        setMessage(classified.message);
        setStatus(classified.status);
      });
  }, []);

  return { result, status, message, answered, run };
}
