import { getToken, reportUnauthorized } from '../auth/session';

// Hand-written types for the historical replay stream. Deliberately separate
// from schema.d.ts: the SSE frames carry no response_model on the backend, so
// there is nothing for openapi-typescript to generate — the shapes mirror
// quantlab.replay.engine's dataclasses and its to_dict() framing.

export interface ReplayBarEvent {
  event: 'bar';
  date: string;
  /** Null where the data had no usable close (NaN is stored as null). */
  closes: Record<string, number | null>;
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
  /** Null when undefined -- a NaN close makes the book's mark NaN. */
  equity: number | null;
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
  /** These three are null when undefined (a NaN close); render a dash. */
  final_equity: number | null;
  total_return: number | null;
  /** Null when not measurable; render a dash, never a zero. */
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  trade_count: number;
  winning_trades: number;
  losing_trades: number;
  assumptions: string[];
  /**
   * True when the run predates recorded replays and this one was rebuilt by
   * re-executing it on later data -- it may differ from what the run did.
   */
  reconstructed?: boolean;
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
  /** The run's replay is still being prepared server-side; retrying. */
  onPreparing?: () => void;
}

export interface ReplayStream {
  close: () => void;
}

const STREAM_FAILED = 'The replay stream failed or was closed before the summary arrived.';

/**
 * A run older than recorded replays gets its replay rebuilt once, in the
 * background; until then the server answers 409 with Retry-After. Waited out
 * this many times before giving up (a 409 without Retry-After -- a failed run
 * -- is final at once).
 */
export const PREPARING_ATTEMPTS = 120;
const MAX_RETRY_AFTER_MS = 30_000;
export const STILL_PREPARING =
  "This run's replay is still being prepared in the background. Nothing is wrong; " +
  'try again later.';

/** Milliseconds a 409 "being prepared" asks to wait, or null if it is final. */
function retryAfterMs(response: Response): number | null {
  if (response.status !== 409) return null;
  const header = response.headers.get('Retry-After');
  if (header === null) return null;
  const seconds = Number(header);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return Math.min(seconds * 1000, MAX_RETRY_AFTER_MS);
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal.addEventListener('abort', done, { once: true });
  });
}

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
  const { intervalMs = 0, step = 1, onEvent, onError, onPreparing } = options;
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
    for (let attempt = 1; ; attempt++) {
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
      const delay = retryAfterMs(response);
      if (delay === null || attempt >= PREPARING_ATTEMPTS) break;
      // Release the refused response's body before asking again.
      void response.body?.cancel().catch(() => {});
      onPreparing?.();
      await wait(delay, abort.signal);
      if (over) return;
    }

    if (!response.ok || !response.body) {
      if (response.status === 401) reportUnauthorized();
      if (retryAfterMs(response) !== null) {
        // Gave up waiting, not refused: say it will be ready later.
        fail(STILL_PREPARING);
        return;
      }
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
