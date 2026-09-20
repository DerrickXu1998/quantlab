// Hand-written types for the historical replay stream. Deliberately separate
// from schema.d.ts: the SSE frames carry no response_model on the backend, so
// there is nothing for openapi-typescript to generate — the shapes mirror
// quantlab.replay.engine's dataclasses and its to_dict() framing.

export interface ReplayBarEvent {
  event: 'bar';
  date: string;
  closes: Record<string, number>;
}

export interface ReplaySignalEvent {
  event: 'signal';
  date: string;
  symbol: string;
  direction: 'bullish' | 'bearish';
  trigger_values: Record<string, unknown>;
  data_window_end: string;
}

export interface ReplayFillEvent {
  event: 'fill';
  date: string;
  symbol: string;
  side: 'buy' | 'sell';
  qty: number;
  price: number;
  value: number;
  realized_pnl: number;
}

export interface ReplayEquityEvent {
  event: 'equity';
  date: string;
  equity: number;
  cash: number;
  /** Open positions at the mark — the engine's `positions` field. */
  positions: number;
  realized_pnl: number;
}

/** Terminal frame; a stream that ended without one did not finish. */
export interface ReplaySummaryEvent {
  event: 'summary';
  run_id: string;
  days: number;
  initial_cash: number;
  final_equity: number;
  total_return: number;
  /** Null when not measurable; render a dash, never a zero. */
  sharpe_ratio: number | null;
  max_drawdown: number;
  win_rate: number | null;
  trade_count: number;
  winning_trades: number;
  losing_trades: number;
  assumptions: string[];
}

export interface ReplayTruncatedEvent {
  event: 'truncated';
  detail: string;
}

export type ReplayEvent =
  | ReplayBarEvent
  | ReplaySignalEvent
  | ReplayFillEvent
  | ReplayEquityEvent
  | ReplaySummaryEvent
  | ReplayTruncatedEvent;

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export function replayStreamUrl(
  runId: string,
  { intervalMs = 0, step = 1 }: { intervalMs?: number; step?: number } = {},
): string {
  const url = new URL(
    `${BASE_URL}/runs/${encodeURIComponent(runId)}/replay/stream`,
    window.location.origin,
  );
  url.searchParams.set('interval_ms', String(intervalMs));
  url.searchParams.set('step', String(step));
  return url.toString();
}

export interface ReplayStreamOptions {
  intervalMs?: number;
  step?: number;
  onEvent: (event: ReplayEvent) => void;
  /** The stream failed (or the run cannot be replayed); the source is closed. */
  onError?: (message: string) => void;
}

export interface ReplayStream {
  close: () => void;
}

/**
 * One run's replay as an EventSource. The backend emits bare `data:` frames,
 * so everything arrives on the default `message` channel.
 *
 * EventSource would silently reconnect after a dropped connection, which for a
 * replay means the stream restarts from day one and double-counts every event.
 * An error therefore closes the source for good; starting over is the caller's
 * explicit act, not the transport's.
 */
export function streamReplay(runId: string, options: ReplayStreamOptions): ReplayStream {
  const { intervalMs = 0, step = 1, onEvent, onError } = options;
  const source = new EventSource(replayStreamUrl(runId, { intervalMs, step }));
  let failed = false;

  source.onmessage = (message: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(message.data) as ReplayEvent);
    } catch {
      // An unparseable frame says nothing; drop it rather than kill the run.
    }
  };
  source.onerror = () => {
    if (failed) return;
    failed = true;
    source.close();
    onError?.('The replay stream failed or was closed before the summary arrived.');
  };

  return {
    close: () => {
      failed = true;
      source.close();
    },
  };
}
