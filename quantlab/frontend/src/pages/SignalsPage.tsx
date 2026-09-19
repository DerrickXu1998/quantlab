import { useEffect, useState } from 'react';
import {
  getPrices,
  listInstruments,
  listSignals,
  type Instrument,
  type PriceBar,
  type Signal,
} from '../api/client';
import { PriceChart } from '../components/PriceChart';
import { EMPTY_FILTERS, SignalFilters, type SignalFilterState } from '../components/SignalFilters';
import { SignalTable } from '../components/SignalTable';
import { BackendUnavailable, Loading } from '../components/StatusStates';

const PAGE_SIZE = 50;

type Status = 'loading' | 'ready' | 'error';

export function SignalsPage() {
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [filters, setFilters] = useState<SignalFilterState>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<Status>('loading');
  const [errorMessage, setErrorMessage] = useState<string>();
  const [selected, setSelected] = useState<Signal | null>(null);
  const [contextBars, setContextBars] = useState<PriceBar[] | null>(null);

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

  const handleFiltersChange = (next: SignalFilterState) => {
    setFilters(next);
    setPage(0);
  };

  return (
    <div className="signals-page">
      <h1>Signal Viewer</h1>

      <SignalFilters instruments={instruments} value={filters} onChange={handleFiltersChange} />

      {status === 'loading' && <Loading />}
      {status === 'error' && <BackendUnavailable message={errorMessage} />}
      {status === 'ready' && (
        <SignalTable
          signals={signals}
          total={total}
          selectedId={selected?.id ?? null}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
          onSelect={setSelected}
        />
      )}

      {selected && (
        <aside className="signal-context" aria-label="Signal context">
          <h2>
            {selected.symbol} — {selected.rule_name} v{selected.rule_version} on {selected.date}
          </h2>
          {contextBars ? (
            <PriceChart bars={contextBars} markerDate={selected.date} />
          ) : (
            <p role="status">Loading price history…</p>
          )}
        </aside>
      )}
    </div>
  );
}
