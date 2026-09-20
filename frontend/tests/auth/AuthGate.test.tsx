import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import { DatasetProvider } from '../../src/api/DatasetProvider';
import { AuthGate } from '../../src/auth/AuthGate';
import { AuthProvider } from '../../src/auth/AuthProvider';
import { setToken } from '../../src/auth/session';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return { ...actual, getHealth: vi.fn(), getMe: vi.fn() };
});

const health = {
  status: 'ok' as const,
  dataset: 'sqlite' as const,
  seeded: true,
  signal_count: 933,
};

function renderGate() {
  return render(
    <AuthProvider>
      <DatasetProvider>
        <AuthGate>
          <p>the workspace</p>
        </AuthGate>
      </DatasetProvider>
    </AuthProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  setToken(null);
  window.localStorage.clear();
});

describe('AuthGate', () => {
  it('lets the single-user demo boot straight into the app', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue({ ...health, auth_required: false });

    renderGate();

    // QUANTLAB_AUTH_REQUIRED=false is a supported mode, not a loophole: there
    // is no account to create, so there must be no wall.
    expect(await screen.findByText('the workspace')).toBeInTheDocument();
    expect(screen.queryByTestId('login-screen')).not.toBeInTheDocument();
    expect(apiClient.getMe).not.toHaveBeenCalled();
  });

  it('shows the login screen when the API says auth is required and nobody is signed in', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue({ ...health, auth_required: true });

    renderGate();

    expect(await screen.findByTestId('login-screen')).toBeInTheDocument();
    expect(screen.queryByText('the workspace')).not.toBeInTheDocument();
  });

  it('lets a validated session through to the workspace', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue({ ...health, auth_required: true });
    vi.mocked(apiClient.getMe).mockResolvedValue({
      id: 'user-1',
      email: 'quant@example.com',
      created_at: '2026-09-01T00:00:00Z',
    });
    setToken('good-token');

    renderGate();

    expect(await screen.findByText('the workspace')).toBeInTheDocument();
  });

  it('does not put a login wall in front of a backend that cannot be reached', async () => {
    vi.mocked(apiClient.getHealth).mockRejectedValue(new apiClient.ApiError(0, 'unreachable'));

    renderGate();

    // The destinations have their own "backend unreachable" states, and those
    // say far more than a login form that is also about to fail.
    await waitFor(() => expect(screen.getByText('the workspace')).toBeInTheDocument());
  });

  it('waits rather than flashing a login screen before health has answered', () => {
    vi.mocked(apiClient.getHealth).mockReturnValue(new Promise(() => undefined));

    renderGate();

    expect(screen.getByRole('status')).toHaveTextContent(/contacting the api/i);
    expect(screen.queryByTestId('login-screen')).not.toBeInTheDocument();
    expect(screen.queryByText('the workspace')).not.toBeInTheDocument();
  });
});
