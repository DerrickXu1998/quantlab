import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  parseSseFrames,
  replayStreamUrl,
  streamReplay,
  type ReplayEvent,
} from '../../src/api/replay';
import { getToken, setToken } from '../../src/auth/session';
import { ReplayPanel } from '../../src/quantlab/panels/ReplayPanel';
import { ThemeProvider } from '../../src/theme/ThemeProvider';
import { installCanvas2d } from '../mocks/canvas-2d';
import { installResizeObserver } from '../mocks/resize-observer';
import { makeRun } from './fixtures';

installResizeObserver();
installCanvas2d();

/**
 * A controllable replay stream behind a stubbed fetch: the code under test
 * reads a real ReadableStream, the test enqueues SSE frames and failures by
 * hand. Each call settles the reader before returning, so an assertion after
 * `await act(() => source.emit(...))` sees the rendered result.
 */
const encoder = new TextEncoder();

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

class FakeStream {
  static instances: FakeStream[] = [];
  /** Set by a test to make the next fetch a refusal instead of a stream. */
  static refuseNext: { status: number; body: unknown } | null = null;

  readonly url: string;
  readonly headers: Record<string, string>;
  closed = false;
  private controller!: ReadableStreamDefaultController<Uint8Array>;

  constructor(url: string, init: RequestInit) {
    this.url = url;
    this.headers = (init.headers ?? {}) as Record<string, string>;
    init.signal?.addEventListener('abort', () => {
      this.closed = true;
      try {
        this.controller.error(new DOMException('aborted', 'AbortError'));
      } catch {
        // already closed or errored
      }
    });
    FakeStream.instances.push(this);
  }

  response(): Response {
    const refusal = FakeStream.refuseNext;
    FakeStream.refuseNext = null;
    if (refusal) {
      return new Response(JSON.stringify(refusal.body), {
        status: refusal.status,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const body = new ReadableStream<Uint8Array>({
      start: (controller) => {
        this.controller = controller;
      },
    });
    return { ok: true, status: 200, body } as Response;
  }

  /** Raw bytes, for frames split across chunks. */
  async write(text: string): Promise<void> {
    this.controller.enqueue(encoder.encode(text));
    await settle();
  }

  emit(event: ReplayEvent): Promise<void> {
    return this.write(`data: ${JSON.stringify(event)}\n\n`);
  }

  async fail(): Promise<void> {
    try {
      this.controller.error(new TypeError('network error'));
    } catch {
      // already closed or errored
    }
    await settle();
  }

  static latest(): FakeStream {
    const latest = FakeStream.instances.at(-1);
    if (!latest) throw new Error('no replay stream was opened');
    return latest;
  }
}

vi.stubGlobal(
  'fetch',
  vi.fn((url: string, init: RequestInit) => Promise.resolve(new FakeStream(url, init).response())),
);

afterEach(() => {
  FakeStream.instances = [];
  FakeStream.refuseNext = null;
  setToken(null);
});

const run = makeRun(); // 2024-01-01 → 2024-12-31, completed, ZZTRND

function equityEvent(date: string, equity: number, cash = 50_000): ReplayEvent {
  return { event: 'equity', date, equity, cash, positions: 2, realized_pnl: 123.45 };
}

const summaryEvent: ReplayEvent = {
  event: 'summary',
  run_id: 'run-1',
  days: 3,
  initial_cash: 100_000,
  final_equity: 123_210.5,
  total_return: 0.2321,
  sharpe_ratio: 2.495,
  max_drawdown: -0.049,
  win_rate: 0.6,
  trade_count: 7,
  winning_trades: 5,
  losing_trades: 2,
  assumptions: ['Long-only.', 'No transaction costs and no slippage are charged.'],
};

function renderPanel(runs = [run]) {
  return render(
    <ThemeProvider>
      <ReplayPanel runs={runs} />
    </ThemeProvider>,
  );
}

async function startReplay() {
  const user = userEvent.setup();
  renderPanel();
  await user.click(screen.getByRole('button', { name: /^play$/i }));
  return user;
}

describe('streamReplay', () => {
  it('builds the stream URL from the shared /api/v1 base', () => {
    expect(replayStreamUrl('run-1', { intervalMs: 50, step: 2 })).toBe(
      `${window.location.origin}/api/v1/runs/run-1/replay/stream?interval_ms=50&step=2`,
    );
  });

  it('parses bare data: frames off the response body', async () => {
    const seen: ReplayEvent[] = [];
    streamReplay('run-1', { onEvent: (event) => seen.push(event) });

    await FakeStream.latest().emit(equityEvent('2024-01-02', 100_123.4));

    expect(seen).toEqual([equityEvent('2024-01-02', 100_123.4)]);
  });

  it('reassembles a frame split across network chunks', async () => {
    const seen: ReplayEvent[] = [];
    streamReplay('run-1', { onEvent: (event) => seen.push(event) });
    const frame = `data: ${JSON.stringify(equityEvent('2024-01-02', 100_123.4))}\n\n`;
    const source = FakeStream.latest();

    await source.write(frame.slice(0, 17));
    expect(seen).toHaveLength(0);
    await source.write(frame.slice(17));

    expect(seen).toEqual([equityEvent('2024-01-02', 100_123.4)]);
  });

  it('splits several frames and ignores anything that is not data:', () => {
    expect(
      parseSseFrames('data: {"a":1}\n\n: keepalive\n\ndata: {"b":2}\r\n\r\ndata: {"c"'),
    ).toEqual({
      frames: ['{"a":1}', '{"b":2}'],
      rest: 'data: {"c"',
    });
  });

  /**
   * The production bug: EventSource cannot send headers, so wherever sign-in
   * is required every replay was a 401 before its first frame.
   */
  it('sends the session token, which EventSource never could', () => {
    setToken('session-token');
    streamReplay('run-1', { onEvent: () => {} });

    expect(FakeStream.latest().headers.Authorization).toBe('Bearer session-token');
  });

  it('says the session expired on a 401, and drops the dead token', async () => {
    setToken('stale-token');
    FakeStream.refuseNext = { status: 401, body: { detail: 'authentication required' } };
    const errors: string[] = [];

    streamReplay('run-1', { onEvent: () => {}, onError: (message) => errors.push(message) });
    await settle();

    expect(errors).toEqual(['Your session has expired. Sign in again to replay this run.']);
    expect(getToken()).toBeNull();
  });

  it("passes the server's reason through when it refuses a stream", async () => {
    FakeStream.refuseNext = {
      status: 429,
      body: { detail: 'too many concurrent replay streams; wait for one to finish' },
    };
    const errors: string[] = [];

    streamReplay('run-1', { onEvent: () => {}, onError: (message) => errors.push(message) });
    await settle();

    expect(errors[0]).toMatch(/too many concurrent replay streams/);
  });

  it('reports a failure once, closes, and never reconnects to double-count', async () => {
    const errors: string[] = [];
    const seen: ReplayEvent[] = [];
    const stream = streamReplay('run-1', {
      onEvent: (event) => seen.push(event),
      onError: (message) => errors.push(message),
    });
    const source = FakeStream.latest();

    await source.fail();
    await source.fail(); // a second failure must not report twice

    expect(source.closed).toBe(true);
    expect(errors).toHaveLength(1);
    expect(FakeStream.instances).toHaveLength(1);

    stream.close();
    expect(seen).toHaveLength(0);
  });

  it('reports nothing after the caller closes it', async () => {
    const errors: string[] = [];
    const stream = streamReplay('run-1', {
      onEvent: () => {},
      onError: (message) => errors.push(message),
    });

    stream.close();
    await settle();

    expect(FakeStream.latest().closed).toBe(true);
    expect(errors).toHaveLength(0);
  });
});

describe('ReplayPanel', () => {
  it('offers only completed runs — a failed run has nothing to replay', () => {
    const failed = makeRun({ id: 'run-failed', status: 'failed', error: 'boom' });
    renderPanel([run, failed]);

    const select = screen.getByTestId('replay-run-select');
    const options = within(select).getAllByRole('option');
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveAttribute('value', 'run-1');
  });

  it('explains itself when no completed run exists', () => {
    renderPanel([makeRun({ status: 'failed', error: 'boom' })]);

    expect(screen.getByTestId('replay-no-runs')).toHaveTextContent(/no completed runs/i);
  });

  it('renders streamed events incrementally, exactly as they arrive', async () => {
    await startReplay();
    const source = FakeStream.latest();
    expect(source.url).toContain('/api/v1/runs/run-1/replay/stream');

    await act(() => source.emit({ event: 'bar', date: '2024-01-02', closes: { ZZTRND: 161.4 } }));
    expect(screen.getByTestId('replay-prices')).toHaveTextContent('ZZTRND 161.40');
    expect(screen.getByTestId('replay-status')).toHaveTextContent('Streaming');

    await act(() =>
      source.emit({
        event: 'fill',
        date: '2024-01-02',
        symbol: 'ZZTRND',
        side: 'buy',
        qty: 238.47,
        price: 139.78,
        value: 33_319.0,
        realized_pnl: 0,
      }),
    );
    const fills = screen.getByTestId('replay-fills');
    expect(within(fills).getByText('ZZTRND')).toBeInTheDocument();
    expect(within(fills).getByText('buy')).toBeInTheDocument();
    expect(within(fills).getByText('238.47')).toBeInTheDocument();

    // The stat strip shows the wire's numbers verbatim — nothing derived.
    await act(() => source.emit(equityEvent('2024-07-02', 100_123.4)));
    const stats = screen.getByTestId('replay-stats');
    expect(stats).toHaveTextContent('2024-07-02');
    expect(stats).toHaveTextContent('$100,123');
    expect(stats).toHaveTextContent('$50,000');

    const progress = screen.getByTestId('replay-progress');
    expect(progress).toHaveAttribute('role', 'progressbar');
    expect(Number(progress.getAttribute('aria-valuenow'))).toBeGreaterThan(0);
  });

  it('shows the summary card on the terminal frame, with its assumptions', async () => {
    await startReplay();
    const source = FakeStream.latest();

    await act(() => source.emit(equityEvent('2024-01-02', 100_123.4)));
    expect(screen.queryByTestId('replay-summary')).not.toBeInTheDocument();

    await act(() => source.emit(summaryEvent));

    const summary = screen.getByTestId('replay-summary');
    // Straight off the payload: +23.21% and 2.50 are the engine's figures.
    expect(summary).toHaveTextContent('+23.21%');
    expect(summary).toHaveTextContent('2.50');
    expect(summary).toHaveTextContent('-4.90%');
    expect(summary).toHaveTextContent('60.00%');
    expect(summary).toHaveTextContent(/no transaction costs/i);
    expect(screen.getByTestId('replay-status')).toHaveTextContent('Complete');

    // The stream is closed on the terminal frame: a trailing transport error
    // (the server ending its response) must not flip a finished replay.
    expect(source.closed).toBe(true);
    await act(() => source.fail());
    expect(screen.queryByTestId('replay-error')).not.toBeInTheDocument();
    expect(screen.getByTestId('replay-status')).toHaveTextContent('Complete');
  });

  it('pauses the display while the stream continues, then catches up on resume', async () => {
    const user = await startReplay();
    const source = FakeStream.latest();
    await act(() => source.emit(equityEvent('2024-01-02', 100_123.4)));

    await user.click(screen.getByRole('button', { name: /pause/i }));

    expect(screen.getByTestId('replay-status')).toHaveTextContent('Paused');
    // The connection stays open and events keep arriving, held off screen.
    expect(source.closed).toBe(false);
    await act(() => source.emit(equityEvent('2024-01-03', 101_000)));
    expect(screen.getByTestId('replay-stats')).toHaveTextContent('2024-01-02');
    expect(screen.getByTestId('replay-stats')).not.toHaveTextContent('2024-01-03');

    await user.click(screen.getByRole('button', { name: /resume/i }));

    const stats = screen.getByTestId('replay-stats');
    expect(stats).toHaveTextContent('2024-01-03');
    expect(stats).toHaveTextContent('$101,000');
    expect(screen.getByTestId('replay-status')).toHaveTextContent('Streaming');
  });

  it('resets the display and closes the stream on Reset', async () => {
    const user = await startReplay();
    const source = FakeStream.latest();
    await act(() => source.emit(equityEvent('2024-01-02', 100_123.4)));

    await user.click(screen.getByRole('button', { name: /reset/i }));

    expect(source.closed).toBe(true);
    expect(screen.getByTestId('replay-status')).toHaveTextContent('Idle');
    expect(screen.getByTestId('replay-stats')).toHaveTextContent('—');
  });

  it('reports a stream failure as an error, with the source closed', async () => {
    await startReplay();
    const source = FakeStream.latest();

    await act(() => source.fail());

    const error = screen.getByTestId('replay-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(error).toHaveTextContent(/replay stream failed/i);
    expect(source.closed).toBe(true);
    expect(screen.getByTestId('replay-status')).toHaveTextContent('Error');
  });

  it('treats a truncated stream as a prefix, never as a result', async () => {
    await startReplay();
    const source = FakeStream.latest();

    await act(() =>
      source.emit({ event: 'truncated', detail: 'max_events=250000 reached before the summary' }),
    );

    const warning = screen.getByTestId('replay-truncated');
    expect(warning).toHaveAttribute('role', 'alert');
    expect(warning).toHaveTextContent(/max_events=250000/);
    expect(screen.queryByTestId('replay-summary')).not.toBeInTheDocument();
  });

  it('changes pace only from the next play — a running stream keeps its speed', async () => {
    const user = await startReplay();
    expect(FakeStream.latest().url).toContain('interval_ms=50');

    await user.click(screen.getByRole('button', { name: '100 ms' }));
    // No new connection mid-stream.
    expect(FakeStream.instances).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: /reset/i }));
    await user.click(screen.getByRole('button', { name: /^play$/i }));
    expect(FakeStream.latest().url).toContain('interval_ms=100');
  });
});

/**
 * The fitting rules the Replay screen is written to. These are the faults the
 * layout primitives exist to prevent, and none of them is visible in a unit
 * test's output — only in the class contract each container carries.
 */
describe('ReplayPanel fitting', () => {
  /** A Panel renders `<section aria-label={title}>`; its body is the last child. */
  function panelBody(title: string): HTMLElement {
    return screen.getByLabelText(title).lastElementChild as HTMLElement;
  }

  it('presents the speed presets as one control, not one control per line', () => {
    renderPanel();

    const group = screen.getByRole('group', { name: /replay speed/i });
    expect(within(group).getAllByRole('button')).toHaveLength(4);
    // Wrapping as a set is what stops `100 ms` reading as a second control.
    expect(group.className).toContain('flex-wrap');
  });

  it('says what the equity panel will show before anything has streamed', async () => {
    renderPanel();

    expect(screen.getByTestId('replay-equity-empty')).toHaveTextContent(/no equity yet/i);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /^play$/i }));
    await act(() => FakeStream.latest().emit(equityEvent('2024-01-02', 100_123.4)));

    expect(screen.queryByTestId('replay-equity-empty')).not.toBeInTheDocument();
  });

  it('fills the workspace instead of leaving dead ground under the panels', () => {
    renderPanel();

    // The control column takes its cell rather than sitting at its natural
    // height with an empty column beneath it.
    expect(screen.getByLabelText('Replay').className).toContain('flex-1');
    expect(screen.getByLabelText('Equity').className).toContain('flex-');
  });

  it('gives the fill and signal tables a scroll edge, not a clipped row', () => {
    renderPanel();

    for (const title of ['Fills', 'Signals']) {
      const body = panelBody(title);
      expect(body.className).toContain('overflow-y-auto');
      // Without min-h-0 the body grows to its table and the panel boundary
      // cuts through a row instead of scrolling.
      expect(body.className).toContain('min-h-0');
    }
  });
});
