import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import type { EquityPoint } from '../../api/client';
import {
  streamReplay,
  type ReplayEvent,
  type ReplayFillEvent,
  type ReplaySignalEvent,
  type ReplayStream,
  type ReplaySummaryEvent,
} from '../../api/replay';

export type ReplayStatus =
  | 'idle'
  | 'connecting'
  | 'streaming'
  | 'paused'
  | 'done'
  | 'truncated'
  | 'error';

export interface ReplayState {
  status: ReplayStatus;
  /** One point per equity event, in stream order. */
  equity: EquityPoint[];
  /** Latest book state, straight off the wire. */
  equityNow: { equity: number; cash: number; positions: number; realizedPnl: number } | null;
  closes: Record<string, number>;
  currentDate: string | null;
  /** Newest first, capped for the DOM. */
  fills: ReplayFillEvent[];
  signals: ReplaySignalEvent[];
  summary: ReplaySummaryEvent | null;
  /** Set on a `truncated` frame; the summary never follows one. */
  truncation: string | null;
  error: string | null;
}

const INITIAL: ReplayState = {
  status: 'idle',
  equity: [],
  equityNow: null,
  closes: {},
  currentDate: null,
  fills: [],
  signals: [],
  summary: null,
  truncation: null,
  error: null,
};

// The tables are a viewport onto the stream, not an archive of it — a replay
// can run to 250k frames, and no one scrolls that.
const MAX_ROWS = 100;

type Action =
  | { type: 'reset' }
  | { type: 'connecting' }
  | { type: 'paused' }
  | { type: 'error'; message: string }
  | { type: 'event'; event: ReplayEvent };

function reduce(state: ReplayState, action: Action): ReplayState {
  if (action.type === 'reset') return INITIAL;
  if (action.type === 'connecting') return { ...state, status: 'connecting' };
  if (action.type === 'paused') {
    return state.status === 'streaming' ? { ...state, status: 'paused' } : state;
  }
  if (action.type === 'error') {
    return { ...state, status: 'error', error: action.message };
  }

  const event = action.event;
  switch (event.event) {
    case 'bar':
      return {
        ...state,
        status: 'streaming',
        currentDate: event.date,
        closes: { ...state.closes, ...event.closes },
      };
    case 'signal':
      return {
        ...state,
        currentDate: event.date,
        signals: [event, ...state.signals].slice(0, MAX_ROWS),
      };
    case 'fill':
      return {
        ...state,
        currentDate: event.date,
        fills: [event, ...state.fills].slice(0, MAX_ROWS),
      };
    case 'equity':
      return {
        ...state,
        status: 'streaming',
        currentDate: event.date,
        equityNow: {
          equity: event.equity,
          cash: event.cash,
          positions: event.positions,
          realizedPnl: event.realized_pnl,
        },
        equity: [...state.equity, { date: event.date, value: event.equity }],
      };
    case 'summary':
      return { ...state, status: 'done', summary: event };
    case 'truncated':
      return { ...state, status: 'truncated', truncation: event.detail };
    default:
      return state;
  }
}

export interface ReplayControls {
  state: ReplayState;
  play: () => void;
  pause: () => void;
  /** Close the stream and clear everything received so far. */
  restart: () => void;
}

/**
 * The replay stream as renderable state. Everything shown is a server-computed
 * event rendered as it arrived (Constitution V) — the only list-building here
 * is appending what the wire sent.
 *
 * Pause freezes the display, not the stream: events that arrive while paused
 * queue up and render together on resume, so the book never silently diverges
 * from what the engine emitted. The stream has no resume offset — a paused
 * replay could otherwise only start over.
 */
export function useReplay(runId: string | null, intervalMs: number): ReplayControls {
  const [state, dispatch] = useReducer(reduce, INITIAL);
  const streamRef = useRef<ReplayStream | null>(null);
  const pausedRef = useRef(false);
  const bufferRef = useRef<ReplayEvent[]>([]);

  const stop = useCallback(() => {
    streamRef.current?.close();
    streamRef.current = null;
  }, []);

  const play = useCallback(() => {
    if (!runId) return;
    // Already live: resume by flushing whatever queued up while paused.
    if (streamRef.current && pausedRef.current) {
      pausedRef.current = false;
      const buffered = bufferRef.current;
      bufferRef.current = [];
      for (const event of buffered) {
        dispatch({ type: 'event', event });
        if (event.event === 'summary' || event.event === 'truncated') stop();
      }
      return;
    }
    stop();
    pausedRef.current = false;
    bufferRef.current = [];
    dispatch({ type: 'reset' });
    dispatch({ type: 'connecting' });
    streamRef.current = streamReplay(runId, {
      intervalMs,
      onEvent: (event) => {
        if (pausedRef.current) {
          bufferRef.current.push(event);
          return;
        }
        dispatch({ type: 'event', event });
        // Close on the terminal frame: the server ending its response would
        // otherwise read as a stream that stopped before its summary.
        if (event.event === 'summary' || event.event === 'truncated') stop();
      },
      onError: (message) => {
        stop();
        dispatch({ type: 'error', message });
      },
    });
  }, [runId, intervalMs, stop]);

  const pause = useCallback(() => {
    if (!streamRef.current || pausedRef.current) return;
    pausedRef.current = true;
    dispatch({ type: 'paused' });
  }, []);

  const restart = useCallback(() => {
    stop();
    pausedRef.current = false;
    bufferRef.current = [];
    dispatch({ type: 'reset' });
  }, [stop]);

  // Changing the run or the speed abandons the old stream; leaving the view
  // closes whichever stream is open.
  useEffect(() => restart, [runId, restart]);
  useEffect(() => stop, [stop]);

  return useMemo(() => ({ state, play, pause, restart }), [state, play, pause, restart]);
}
