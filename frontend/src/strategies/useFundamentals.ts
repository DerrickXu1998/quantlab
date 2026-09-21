import { useEffect, useState } from 'react';
import { ApiError, getFundamentals, getFundamentalsCoverage } from '../api/client';
import type { FundamentalFact, FundamentalsCoverage } from '../api/types';

/**
 * Reads of the fundamentals warehouse, with the states it can really be in.
 *
 * Four, not three. `unsupported` is the one that matters while the backend is
 * being written in parallel: a 404 from `/fundamentals/coverage` means this
 * deployment does not serve fundamentals, which is a different fact from "the
 * backend fell over" and a very different fact from "nothing is covered".
 * Collapsing them would put a coverage warning on a strategy nobody can check,
 * or — worse — an all-clear on one nobody asked about.
 */
export type FundamentalsStatus = 'loading' | 'ready' | 'unsupported' | 'error';

function classify(caught: unknown): { status: FundamentalsStatus; message: string } {
  if (caught instanceof ApiError && caught.status === 404) {
    return {
      status: 'unsupported',
      message: 'This backend does not serve fundamentals.',
    };
  }
  return {
    status: 'error',
    message: caught instanceof ApiError ? caught.message : 'the fundamentals warehouse is unreachable',
  };
}

export interface CoverageRead {
  coverage: FundamentalsCoverage | null;
  status: FundamentalsStatus;
  message: string | null;
  reload: () => void;
}

/**
 * Which instruments and concepts have filings at all.
 *
 * `enabled` is normally "does this registry have a fundamental rule in it?".
 * A deployment with no fundamental rules has nothing to warn about, and asking
 * anyway would spend a request to render nothing.
 */
export function useFundamentalsCoverage(enabled = true): CoverageRead {
  const [coverage, setCoverage] = useState<FundamentalsCoverage | null>(null);
  const [status, setStatus] = useState<FundamentalsStatus>(enabled ? 'loading' : 'ready');
  const [message, setMessage] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setStatus('loading');
    getFundamentalsCoverage()
      .then((result) => {
        if (cancelled) return;
        setCoverage(result);
        setMessage(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const classified = classify(caught);
        setCoverage(null);
        setMessage(classified.message);
        setStatus(classified.status);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, nonce]);

  return { coverage, status, message, reload: () => setNonce((value) => value + 1) };
}

export interface FactsRead {
  facts: FundamentalFact[];
  status: FundamentalsStatus;
  message: string | null;
  reload: () => void;
}

/**
 * One instrument's filed facts as of one date.
 *
 * Re-read whenever either changes, because both are the question: the same
 * symbol on two dates is two different answers, and that is the entire point
 * of the inspector.
 */
export function useInstrumentFacts(symbol: string | null, asOf: string): FactsRead {
  const [facts, setFacts] = useState<FundamentalFact[]>([]);
  const [status, setStatus] = useState<FundamentalsStatus>('loading');
  const [message, setMessage] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!symbol || !asOf) {
      setFacts([]);
      setStatus('ready');
      setMessage(null);
      return;
    }
    let cancelled = false;
    setStatus('loading');
    getFundamentals(symbol, asOf)
      .then((result) => {
        if (cancelled) return;
        setFacts(result);
        setMessage(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const classified = classify(caught);
        setFacts([]);
        setMessage(classified.message);
        setStatus(classified.status);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, asOf, nonce]);

  return { facts, status, message, reload: () => setNonce((value) => value + 1) };
}
