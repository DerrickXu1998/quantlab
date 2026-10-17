import { getToken, reportUnauthorized } from '../auth/session';
import type { LiveEvent } from './client';
import { parseSseFrames } from './replay';

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export function liveStreamUrl(symbols: string[]): string {
  const url = new URL(`${BASE_URL}/live/stream`, window.location.origin);
  url.searchParams.set('symbols', symbols.join(','));
  return url.toString();
}

export interface LiveStreamHandlers {
  /** The server accepted the stream; frames follow. */
  onOpen?: () => void;
  onEvent: (event: LiveEvent) => void;
  /**
   * The stream is over: refused (`status` is the HTTP status), dropped
   * (`status` 0) or ended by the server's hourly cut-off (`status` 200).
   * Never called after `close()`.
   */
  onEnd: (status: number, message: string) => void;
}

export interface LiveStream {
  close: () => void;
}

async function refusal(response: Response): Promise<string> {
  if (response.status === 401) return 'Your session has expired. Sign in again for live prices.';
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (body.detail) return String(body.detail);
  } catch {
    // no JSON body; fall through to the status
  }
  return `The live feed could not start (HTTP ${response.status}).`;
}

/**
 * One live stream for a set of symbols, read with fetch so it can carry the
 * bearer token (EventSource cannot send headers; see streamReplay).
 *
 * One connection, no retries of its own: the live feed store owns the
 * reconnect policy, because only it knows whether the symbol set changed in
 * the meantime. Unlike a replay, reopening a live stream is always safe --
 * a tail of the newest prices carries nothing to double-count.
 */
export function openLiveStream(symbols: string[], handlers: LiveStreamHandlers): LiveStream {
  const abort = new AbortController();
  let over = false;

  const end = (status: number, message: string) => {
    if (over) return;
    over = true;
    abort.abort();
    handlers.onEnd(status, message);
  };

  void (async () => {
    let response: Response;
    try {
      const token = getToken();
      response = await fetch(liveStreamUrl(symbols), {
        headers: {
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        cache: 'no-store',
        signal: abort.signal,
      });
    } catch {
      end(0, 'The live feed is unreachable.');
      return;
    }

    if (!response.ok || !response.body) {
      if (response.status === 401) reportUnauthorized();
      end(response.status, response.ok ? 'The live feed sent no body.' : await refusal(response));
      return;
    }
    if (!over) handlers.onOpen?.();

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
            handlers.onEvent(JSON.parse(data) as LiveEvent);
          } catch {
            // An unparseable frame says nothing; drop it rather than the feed.
          }
        }
      }
      end(200, 'The live stream ended; reconnecting.');
    } catch {
      end(0, 'The live stream dropped; reconnecting.');
    }
  })();

  return {
    close: () => {
      over = true;
      abort.abort();
    },
  };
}
