import { useEffect, useRef, useState } from 'react';
import { getPrices, type Instrument } from '../api/client';

/** Used when the data extent cannot be read: the demo dataset's window. */
export const FALLBACK_WINDOW = { start: '2024-01-01', end: '2024-12-31' };

export interface DataWindow {
  startDate: string;
  endDate: string;
  setStartDate: (value: string) => void;
  setEndDate: (value: string) => void;
}

/**
 * The date window, defaulted to the actual extent of the stored data.
 *
 * One price read against the first instrument, rather than a hardcoded year —
 * a form that proposes 2024 against a warehouse holding 2019–2026 is proposing
 * a window that is mostly wrong. The backfill never steamrolls an edit the
 * researcher has already made, which is what the touched ref is for.
 *
 * Shared by the single-model run form and the strategy builder so the two
 * cannot disagree about what "the data" means.
 */
export function useDataWindow(instruments: Instrument[]): DataWindow {
  const [startDate, setStart] = useState(FALLBACK_WINDOW.start);
  const [endDate, setEnd] = useState(FALLBACK_WINDOW.end);
  const touched = useRef(false);

  useEffect(() => {
    const first = instruments[0]?.symbol;
    if (!first) return;
    let cancelled = false;
    getPrices(first)
      .then((bars) => {
        if (cancelled || touched.current || bars.items.length === 0) return;
        setStart(bars.items[0].date);
        setEnd(bars.items[bars.items.length - 1].date);
      })
      .catch(() => {
        // The fallback window stays; a missing extent is not an error here.
      });
    return () => {
      cancelled = true;
    };
  }, [instruments]);

  return {
    startDate,
    endDate,
    setStartDate: (value: string) => {
      touched.current = true;
      setStart(value);
    },
    setEndDate: (value: string) => {
      touched.current = true;
      setEnd(value);
    },
  };
}
