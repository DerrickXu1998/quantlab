import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The token lifecycle, exercised through the real API client.
 *
 * `fetch` is stubbed rather than the client mocked: the two behaviours that
 * matter here — the Authorization header going out on every request, and a 401
 * coming back tearing the session down — live *in* the client, and a test that
 * mocked it would be asserting against its own stand-in.
 */

const STORAGE_KEY = 'quantlab.auth.token';

interface StubResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

function reply(status: number, body: unknown = {}): StubResponse {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const fetchMock = vi.fn<[string, RequestInit | undefined], Promise<StubResponse>>();

const user = {
  id: 'user-1',
  email: 'quant@example.com',
  created_at: '2026-09-01T00:00:00Z',
};

async function loadAuth() {
  vi.resetModules();
  const session = await import('../../src/auth/session');
  const provider = await import('../../src/auth/AuthProvider');
  return { session, AuthProvider: provider.AuthProvider, useAuth: provider.useAuth };
}

type UseAuth = Awaited<ReturnType<typeof loadAuth>>['useAuth'];

function makeProbe(useAuth: UseAuth) {
  return function Probe() {
    const { status, user: current, token, login, logout } = useAuth();
    return (
      <div>
        <span data-testid="status">{status}</span>
        <span data-testid="email">{current?.email ?? 'none'}</span>
        <span data-testid="token">{token ?? 'none'}</span>
        <button
          type="button"
          onClick={() => {
            // The screen handles a rejection; the probe only has to not
            // leave an unhandled one behind.
            login({ email: user.email, password: 'hunter22' }).catch(() => undefined);
          }}
        >
          sign in
        </button>
        <button type="button" onClick={() => void logout()}>
          sign out
        </button>
      </div>
    );
  };
}

function lastRequest(): [string, RequestInit | undefined] {
  const call = fetchMock.mock.calls.at(-1);
  if (!call) throw new Error('no request was made');
  return call;
}

function headerOn(call: [string, RequestInit | undefined], name: string): string | undefined {
  return (call[1]?.headers as Record<string, string> | undefined)?.[name];
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('AuthProvider', () => {
  it('boots anonymous, and does not ask the server who a missing token belongs to', async () => {
    const { AuthProvider, useAuth } = await loadAuth();
    const Probe = makeProbe(useAuth);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(screen.getByTestId('status')).toHaveTextContent('anonymous');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('validates a stored token against /auth/me rather than trusting it', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'stored-token');
    fetchMock.mockResolvedValue(reply(200, user));
    const { AuthProvider, useAuth } = await loadAuth();
    const Probe = makeProbe(useAuth);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('email')).toHaveTextContent(user.email);

    const call = lastRequest();
    expect(call[0]).toContain('/api/v1/auth/me');
    // Every request carries the bearer token, which is the whole point of
    // attaching it in the client rather than at each call site.
    expect(headerOn(call, 'Authorization')).toBe('Bearer stored-token');
  });

  it('clears the session when the server answers 401, and persists the clearing', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'revoked-token');
    fetchMock.mockResolvedValue(reply(401, { detail: 'invalid token' }));
    const { AuthProvider, useAuth } = await loadAuth();
    const Probe = makeProbe(useAuth);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'));
    expect(screen.getByTestId('token')).toHaveTextContent('none');
    // A dead token must not survive a reload, or the next boot repeats this.
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('tears the session down exactly once when several requests 401 together', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'revoked-token');
    const { session } = await loadAuth();

    const notified = vi.fn();
    session.subscribeToken(notified);

    session.reportUnauthorized();
    session.reportUnauthorized();
    session.reportUnauthorized();

    // Three 401s, one teardown: this is what keeps the bounce to the login
    // screen from becoming a redirect loop.
    expect(notified).toHaveBeenCalledTimes(1);
    expect(session.getToken()).toBeNull();
  });

  it('adopts the session a successful login returns, without a second round trip', async () => {
    fetchMock.mockResolvedValue(
      reply(200, { user, token: 'fresh-token', expires_at: '2026-10-20T12:00:00Z' }),
    );
    const { AuthProvider, useAuth } = await loadAuth();
    const Probe = makeProbe(useAuth);
    const person = userEvent.setup();

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await person.click(screen.getByRole('button', { name: 'sign in' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('fresh-token');
    // The login response already carried the user; asking /auth/me for it
    // again would be a round trip for something we were just handed.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(lastRequest()[0]).toContain('/api/v1/auth/login');
  });

  it('keeps a session that was already good when a bad login is rejected', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'good-token');
    fetchMock.mockImplementation(async (url: string) =>
      url.includes('/auth/me') ? reply(200, user) : reply(401, { detail: 'nope' }),
    );
    const { AuthProvider, useAuth } = await loadAuth();
    const Probe = makeProbe(useAuth);
    const person = userEvent.setup();

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));

    await person.click(screen.getByRole('button', { name: 'sign in' }));

    // A 401 from the credential endpoints means "wrong password", not "your
    // session died" — logging the user out here would be a nasty surprise.
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1));
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('good-token');
  });

  it('revokes server-side on sign out and drops the token locally either way', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'good-token');
    fetchMock.mockImplementation(async (url: string) =>
      url.includes('/auth/logout') ? reply(204) : reply(200, user),
    );
    const { AuthProvider, useAuth } = await loadAuth();
    const Probe = makeProbe(useAuth);
    const person = userEvent.setup();

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));

    await person.click(screen.getByRole('button', { name: 'sign out' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => url.includes('/auth/logout'))).toBe(true);
  });

  it('still signs in when localStorage throws, as it does in a private window', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    fetchMock.mockResolvedValue(
      reply(200, { user, token: 'fresh-token', expires_at: '2026-10-20T12:00:00Z' }),
    );
    const { AuthProvider, useAuth } = await loadAuth();
    const Probe = makeProbe(useAuth);
    const person = userEvent.setup();

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await person.click(screen.getByRole('button', { name: 'sign in' }));

    // The session does not survive a reload, but the tab works — which is a
    // far better failure than the app refusing to load at all.
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('token')).toHaveTextContent('fresh-token');
  });
});
