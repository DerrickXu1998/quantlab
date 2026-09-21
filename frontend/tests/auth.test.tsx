import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as authApi from '../src/api/auth';
import * as apiClient from '../src/api/client';
import { DatasetProvider } from '../src/api/DatasetProvider';
import { reportSessionExpired } from '../src/api/session';
import { AuthGate } from '../src/auth/AuthGate';
import { AppShell } from '../src/chrome/AppShell';
import { RunsProvider } from '../src/runs/RunsContext';
import { ThemeProvider } from '../src/theme/ThemeProvider';
import { installCanvas2d } from './mocks/canvas-2d';
import { installResizeObserver } from './mocks/resize-observer';
import { makePerformance, makeRun, model } from './quantlab/fixtures';

vi.mock('../src/api/auth');
vi.mock('../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    getHealth: vi.fn(),
    listInstruments: vi.fn(),
    getPrices: vi.fn(),
    listSignals: vi.fn(),
    listModels: vi.fn(),
    listRuns: vi.fn(),
    getRun: vi.fn(),
    getRunPerformance: vi.fn(),
    saveRun: vi.fn(),
    deleteRun: vi.fn(),
  };
});

installResizeObserver();
installCanvas2d();

const admin = { id: 1, username: 'admin', is_admin: true };

beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = '';
  vi.mocked(authApi.fetchCurrentUser).mockRejectedValue(
    new apiClient.ApiError(401, 'not authenticated'),
  );
  vi.mocked(apiClient.getHealth).mockResolvedValue({
    status: 'ok',
    dataset: 'sqlite',
    seeded: true,
    signal_count: 933,
  });
  vi.mocked(apiClient.listInstruments).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.getPrices).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listSignals).mockResolvedValue({ total: 0, items: [] });
  vi.mocked(apiClient.listModels).mockResolvedValue({ total: 1, items: [model] });
  vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 1, items: [makeRun()] });
  vi.mocked(apiClient.getRun).mockResolvedValue(makeRun());
  vi.mocked(apiClient.getRunPerformance).mockResolvedValue(makePerformance());
});

/** The gate around a stand-in for the app, for the flow tests. */
function renderGate() {
  return render(
    <AuthGate>
      <div data-testid="protected-app" />
    </AuthGate>,
  );
}

/** The gate around the real shell, for the session-chrome tests. */
function renderShellInGate() {
  return render(
    <ThemeProvider>
      <AuthGate>
        <DatasetProvider>
          <RunsProvider>
            <AppShell />
          </RunsProvider>
        </DatasetProvider>
      </AuthGate>
    </ThemeProvider>,
  );
}

async function submitCredentials(user: ReturnType<typeof userEvent.setup>, name = 'admin') {
  await user.type(screen.getByLabelText(/username/i), name);
  // Enter in the password field submits the form.
  await user.type(screen.getByLabelText(/password/i), 'hunter22{enter}');
}

describe('AuthGate', () => {
  it('shows a checking state while the session is resolved', () => {
    vi.mocked(authApi.fetchCurrentUser).mockReturnValue(new Promise(() => {}));

    renderGate();

    expect(screen.getByRole('status', { name: /checking session/i })).toBeInTheDocument();
    expect(screen.queryByTestId('protected-app')).not.toBeInTheDocument();
  });

  it('moves from checking to the sign-in card when unauthenticated', async () => {
    renderGate();

    expect(screen.getByRole('status', { name: /checking session/i })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByTestId('protected-app')).not.toBeInTheDocument();
  });

  it('goes straight into the app when auth is disabled (404 on /auth/me)', async () => {
    vi.mocked(authApi.fetchCurrentUser).mockRejectedValue(
      new apiClient.ApiError(404, 'authentication is disabled (QUANTLAB_AUTH=off)'),
    );

    renderShellInGate();

    expect(await screen.findByTestId('feed-status')).toBeInTheDocument();
    // No session chrome in demo mode: no username, no logout.
    expect(screen.queryByTestId('session-user')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /log out/i })).not.toBeInTheDocument();
  });

  it('signs in and shows the shell with the username, keeping the deep link', async () => {
    window.location.hash = '#/market';
    vi.mocked(authApi.login).mockResolvedValue(admin);

    const user = userEvent.setup();
    renderShellInGate();
    await screen.findByRole('heading', { name: /sign in/i });

    await submitCredentials(user);

    expect(authApi.login).toHaveBeenCalledWith({ username: 'admin', password: 'hunter22' });
    expect(await screen.findByTestId('session-user')).toHaveTextContent('admin');
    // The hash router was never touched: the deep link survives sign-in.
    expect(window.location.hash).toBe('#/market');
  });

  it('reports bad credentials inline', async () => {
    vi.mocked(authApi.login).mockRejectedValue(
      new apiClient.ApiError(401, 'invalid username or password'),
    );

    const user = userEvent.setup();
    renderGate();
    await screen.findByRole('heading', { name: /sign in/i });

    await submitCredentials(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid username or password/i);
    expect(screen.queryByTestId('protected-app')).not.toBeInTheDocument();
  });

  it('says to wait when the login is rate limited', async () => {
    vi.mocked(authApi.login).mockRejectedValue(
      new apiClient.ApiError(429, 'too many attempts; try again later'),
    );

    const user = userEvent.setup();
    renderGate();
    await screen.findByRole('heading', { name: /sign in/i });

    await submitCredentials(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /too many attempts.*wait a minute/i,
    );
  });

  it('refuses a password under 8 characters without calling the backend', async () => {
    const user = userEvent.setup();
    renderGate();
    await screen.findByRole('heading', { name: /sign in/i });

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText(/password/i), 'short{enter}');

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least 8 characters/i);
    expect(authApi.login).not.toHaveBeenCalled();
  });

  it('creates the first admin account from the setup card, then signs in', async () => {
    vi.mocked(authApi.register).mockResolvedValue(admin);
    vi.mocked(authApi.login).mockResolvedValue(admin);

    const user = userEvent.setup();
    renderShellInGate();
    await screen.findByRole('heading', { name: /sign in/i });

    await user.click(screen.getByRole('button', { name: /create the admin account/i }));
    expect(
      await screen.findByRole('heading', { name: /create the admin account/i }),
    ).toBeInTheDocument();

    await submitCredentials(user);

    // Register sets no cookie, so the gate signs in with the same credentials.
    expect(authApi.register).toHaveBeenCalledWith({ username: 'admin', password: 'hunter22' });
    expect(authApi.login).toHaveBeenCalledWith({ username: 'admin', password: 'hunter22' });
    expect(await screen.findByTestId('session-user')).toHaveTextContent('admin');
  });

  it('reports a taken username on setup', async () => {
    vi.mocked(authApi.register).mockRejectedValue(
      new apiClient.ApiError(409, 'username taken: admin'),
    );

    const user = userEvent.setup();
    renderGate();
    await screen.findByRole('heading', { name: /sign in/i });
    await user.click(screen.getByRole('button', { name: /create the admin account/i }));

    await submitCredentials(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(/username is taken/i);
    expect(authApi.login).not.toHaveBeenCalled();
  });

  it('returns to the sign-in card on logout', async () => {
    vi.mocked(authApi.fetchCurrentUser).mockResolvedValue({ id: 1, username: 'admin' });
    vi.mocked(authApi.logout).mockResolvedValue(undefined);

    const user = userEvent.setup();
    renderShellInGate();

    await user.click(await screen.findByRole('button', { name: /log out/i }));

    expect(authApi.logout).toHaveBeenCalled();
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByTestId('session-user')).not.toBeInTheDocument();
  });

  it('collapses to the sign-in card when a data endpoint answers 401', async () => {
    vi.mocked(authApi.fetchCurrentUser).mockResolvedValue({ id: 1, username: 'admin' });

    renderGate();
    await screen.findByTestId('protected-app');

    act(() => reportSessionExpired());

    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByTestId('protected-app')).not.toBeInTheDocument();
  });
});
