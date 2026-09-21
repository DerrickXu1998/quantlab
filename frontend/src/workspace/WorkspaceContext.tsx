import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  getPrices,
  listInstruments,
  listSignals,
  type Instrument,
  type PriceBar,
  type Signal,
} from '../api/client';
import { EMPTY_FILTERS, type SignalFilterState } from '../components/SignalFilters';

export const PAGE_SIZE = 50;

export type Status = 'loading' | 'ready' | 'error';

interface WorkspaceContextValue {
  instruments: Instrument[];
  filters: SignalFilterState;
  changeFilters: (next: SignalFilterState) => void;
  signals: Signal[];
  total: number;
  status: Status;
  errorMessage?: string;
  page: number;
  setPage: (page: number) => void;
  selected: Signal | null;
  setSelected: (signal: Signal) => void;
  contextBars: PriceBar[] | null;
}

const WorkspaceContext = createContext<WorkspaceContextValue | undefined>(undefined);

/**
 * Owns all Signal Viewer state, above the docking layer.
 *
 * This placement is load-bearing, not stylistic: dockview re-parents panel DOM
 * when panels are dragged, which can remount panel components. State held inside
 * a panel would be lost on every rearrange, and rearranging would re-fetch.
 */
export function WorkspaceProvider({
  children,
  instrumentFilter = null,
}: {
  children: ReactNode;
  /** Handoff from another destination ("Signals for X"): applied as the instrument filter. */
  instrumentFilter?: string | null;
}) {
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [filters, setFilters] = useState<SignalFilterState>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<Status>('loading');
  const [errorMessage, setErrorMessage] = useState<string>();
  const [selected, setSelected] = useState<Signal | null>(null);
  const [contextBars, setContextBars] = useState<PriceBar[] | null>(null);

  // Cross-destination handoff: arriving with ?instrument=… pre-filters the table.
  useEffect(() => {
    if (!instrumentFilter) return;
    setFilters({ ...EMPTY_FILTERS, instrument: instrumentFilter });
    setPage(0);
  }, [instrumentFilter]);

  useEffect(() => {
    let cancelled = false;
    listInstruments()
      .then((result) => {
        if (!cancelled) setInstruments(result.items);
      })
      .catch(() => {
        if (!cancelled) {
          setStatus('error');
          setErrorMessage('instrument list could not be loaded');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    listSignals({
      instrument: filters.instrument || undefined,
      signal_type: filters.signalType || undefined,
      direction: filters.direction || undefined,
      start_date: filters.startDate || undefined,
      end_date: filters.endDate || undefined,
      sort: filters.sort,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    })
      .then((result) => {
        if (!cancelled) {
          setSignals(result.items);
          setTotal(result.total);
          setStatus('ready');
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setStatus('error');
          setErrorMessage(error instanceof Error ? error.message : undefined);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [filters, page]);

  useEffect(() => {
    if (!selected) {
      setContextBars(null);
      return;
    }
    let cancelled = false;
    setContextBars(null);
    getPrices(selected.symbol, undefined, undefined)
      .then((result) => {
        if (!cancelled) setContextBars(result.items);
      })
      .catch(() => {
        if (!cancelled) setContextBars([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const changeFilters = (next: SignalFilterState) => {
    setFilters(next);
    setPage(0);
  };

  // The signals API cannot filter by instrument kind, so the kind chip is
  // applied to the loaded page against the instrument list. A signal whose
  // symbol is unknown to the list is excluded under an active kind filter —
  // claiming a kind for it would be a guess.
  const kindBySymbol = useMemo(
    () => new Map(instruments.map((instrument) => [instrument.symbol, instrument.kind])),
    [instruments],
  );
  const visibleSignals = useMemo(
    () =>
      filters.kind
        ? signals.filter((signal) => kindBySymbol.get(signal.symbol) === filters.kind)
        : signals,
    [signals, filters.kind, kindBySymbol],
  );

  return (
    <WorkspaceContext.Provider
      value={{
        instruments,
        filters,
        changeFilters,
        signals: visibleSignals,
        total,
        status,
        errorMessage,
        page,
        setPage,
        selected,
        setSelected,
        contextBars,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error('useWorkspace must be used within a WorkspaceProvider');
  }
  return ctx;
}
