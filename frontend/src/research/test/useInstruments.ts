import { useEffect, useState } from 'react';
import { listInstruments, type Instrument } from '../../api/client';

export type InstrumentsStatus = 'loading' | 'ready' | 'error';

/**
 * The catalogued instruments, for the run form's symbol picker.
 *
 * Read here rather than taken from `WorkspaceContext` on purpose: that
 * provider belongs to the dock this mode replaces, and Test must not require
 * the thing it is retiring to be mounted around it.
 */
export function useInstruments(): { instruments: Instrument[]; status: InstrumentsStatus } {
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [status, setStatus] = useState<InstrumentsStatus>('loading');

  useEffect(() => {
    let cancelled = false;
    listInstruments()
      .then((result) => {
        if (cancelled) return;
        setInstruments(result.items);
        setStatus('ready');
      })
      .catch(() => {
        if (!cancelled) setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { instruments, status };
}
