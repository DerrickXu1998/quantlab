import { getToken, reportUnauthorized } from '../auth/session';

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

const STREAM_FAILED = 'The replay stream failed or was closed before the summary arrived.';

/** Why the server refused to open a stream, in words a person can act on. */
async function refusal(response: Response): Promise<string> {
  if (response.status === 401) {
    return 'Your session has expired. Sign in again to replay this run.';
  }
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (body.detail) return `The replay could not start: ${String(body.detail)}.`;
  } catch {
    // no JSON body; fall through to the status
  }
  return `The replay could not start (HTTP ${response.status}).`;
}

/**
 * The `data:` payloads in one chunk of an SSE body, plus whatever trailing
 * partial frame has to wait for the next chunk. Frames end at a blank line;
 * the backend sends bare `data:` frames with no event names or ids.
 */
export function parseSseFrames(buffer: string): { frames: string[]; rest: string } {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? '';
  const frames = blocks
    .map((block) =>
      block
        .split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).replace(/^ /, ''))
        .join('\n'),
    )
    .filter((data) => data !== '');
  return { frames, rest };
}

/**
 * One run's replay, read with fetch rather than EventSource.
 *
 * EventSource cannot send headers, and the API authenticates with an
 * `Authorization: Bearer` header -- so wherever sign-in is required (that is,
 * production) every replay was refused with a 401 before a single frame, and
 * the panel could only say the stream failed. fetch sends the same header as
 * every other call, and says *why* when the server refuses.
 *
 * It also never reconnects on its own. For a replay that matters: a
 * reconnect restarts from day one and double-counts every event, so an error
 * ends the stream for good and starting over is the caller's explicit act.
 */
export function streamReplay(runId: string, options: ReplayStreamOptions): ReplayStream {
  const { intervalMs = 0, step = 1, onEvent, onError } = options;
  const abort = new AbortController();
  // Set once the stream is over for any reason -- closed by the caller,
  // failed, or ended -- so nothing is reported twice or after a close.
  let over = false;

  const fail = (message: string) => {
    if (over) return;
    over = true;
    abort.abort();
    onError?.(message);
  };

  void (async () => {
    let response: Response;
    try {
      const token = getToken();
      response = await fetch(replayStreamUrl(runId, { intervalMs, step }), {
        headers: {
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        cache: 'no-store',
        signal: abort.signal,
      });
    } catch {
      fail(STREAM_FAILED);
      return;
    }

    if (!response.ok || !response.body) {
      if (response.status === 401) reportUnauthorized();
      fail(response.ok ? STREAM_FAILED : await refusal(response));
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseFrames(buffer);
        buffer = parsed.rest;
        for (const data of parsed.frames) {
          if (over) return;
          try {
            onEvent(JSON.parse(data) as ReplayEvent);
          } catch {
            // An unparseable frame says nothing; drop it rather than kill the run.
          }
        }
      }
    } catch {
      // Aborted by close(), or the connection dropped mid-stream.
    }
    // Ending without the caller closing on a terminal frame means the
    // summary never came.
    fail(STREAM_FAILED);
  })();

  return {
    close: () => {
      over = true;
      abort.abort();
    },
  };
}
