import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, deleteRun, listSignals } from '../src/api/client';
import { onSessionExpired } from '../src/api/session';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('session expiry reporting', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('notifies subscribers when a GET endpoint answers 401', async () => {
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'not authenticated' })),
    );

    await expect(listSignals()).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it('notifies subscribers when a mutation endpoint answers 401', async () => {
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'not authenticated' })),
    );

    await expect(deleteRun('run-1')).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it('stays silent for other failure statuses', async () => {
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    );

    await expect(listSignals()).rejects.toBeInstanceOf(ApiError);
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });

  it('stops notifying after unsubscribe', async () => {
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);
    unsubscribe();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'not authenticated' })),
    );

    await expect(listSignals()).rejects.toMatchObject({ status: 401 });
    expect(listener).not.toHaveBeenCalled();
  });
});
