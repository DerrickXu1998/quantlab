import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import type { UserSettingsDocument } from '../../src/api/client';
import { DatasetProvider } from '../../src/api/DatasetProvider';
import { AuthProvider } from '../../src/auth/AuthProvider';
import { setToken } from '../../src/auth/session';
import { UserMenu } from '../../src/auth/UserMenu';
import { useCustomUniverses } from '../../src/quantlab/market/useMarketData';
import { mergePatch, SettingsProvider } from '../../src/settings/SettingsProvider';
import { ThemeProvider } from '../../src/theme/ThemeProvider';

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    getHealth: vi.fn(),
    getMe: vi.fn(),
    getUserSettings: vi.fn(),
    updateUserSettings: vi.fn(),
    putIbkrCredentials: vi.fn(),
    deleteIbkrCredentials: vi.fn(),
  };
});

const health = { status: 'ok' as const, dataset: 'sqlite' as const, seeded: true, signal_count: 1 };

function doc(over: Partial<UserSettingsDocument> = {}, settings: Partial<UserSettingsDocument['settings']> = {}): UserSettingsDocument {
  return {
    account: { id: 'local', email: null, auth_required: false },
    settings: {
      appearance: { theme: 'dark' },
      market: { default_data: 'historical', lists: [] },
      ibkr: { username: null, trading_mode: 'paper' },
      ...settings,
    },
    updated_at: '2026-10-17T10:00:00+00:00',
    ibkr_connection: { state: 'none' },
    ...over,
  };
}

function renderMenu(children = <UserMenu />) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <DatasetProvider>
          <SettingsProvider>{children}</SettingsProvider>
        </DatasetProvider>
      </AuthProvider>
    </ThemeProvider>,
  );
}

async function openSettings() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: /^Account:/ }));
  await user.click(screen.getByRole('menuitem', { name: 'Settings' }));
  return { user, dialog: await screen.findByRole('dialog', { name: 'Settings' }) };
}

beforeEach(() => {
  vi.clearAllMocks();
  setToken(null);
  window.localStorage.clear();
  document.documentElement.classList.add('dark');
  vi.mocked(apiClient.getHealth).mockResolvedValue({ ...health, auth_required: false });
  vi.mocked(apiClient.getUserSettings).mockResolvedValue(doc());
  // A server with memory: each patch applies to what the last read or write left.
  let current: UserSettingsDocument | null = null;
  vi.mocked(apiClient.updateUserSettings).mockImplementation(async (patch) => {
    current ??= await vi.mocked(apiClient.getUserSettings).getMockImplementation()?.() ?? doc();
    current = { ...current, settings: mergePatch(current.settings, patch) };
    return current;
  });
});

describe('mergePatch', () => {
  it('merges objects, replaces lists and resets on null, as the server does', () => {
    const base = { a: { x: 1, y: 2 }, list: [1, 2], keep: true };
    expect(mergePatch(base, { a: { y: 3 }, list: [9] })).toEqual({ a: { x: 1, y: 3 }, list: [9], keep: true });
    expect(mergePatch(base, { a: null })).toEqual({ list: [1, 2], keep: true });
  });
});

describe('the account menu', () => {
  it('opens settings for the local account when sign-in is off, with no sign-out', async () => {
    renderMenu();
    const { dialog } = await openSettings();
    expect(within(dialog).getByTestId('settings-account')).toHaveTextContent(/local account/i);
    expect(screen.queryByRole('menuitem', { name: /sign out/i })).toBeNull();
  });

  it('names the signed-in account and keeps sign-out', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue({ ...health, auth_required: true });
    vi.mocked(apiClient.getMe).mockResolvedValue({ id: 'u1', email: 'me@example.com', created_at: '2026-01-01' });
    vi.mocked(apiClient.getUserSettings).mockResolvedValue(
      doc({ account: { id: 'u1', email: 'me@example.com', auth_required: true } }),
    );
    setToken('a-token');
    renderMenu();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Account: me@example.com' }));
    expect(screen.getByRole('menuitem', { name: /sign out/i })).toBeInTheDocument();
    await user.click(screen.getByRole('menuitem', { name: 'Settings' }));
    const dialog = await screen.findByRole('dialog', { name: 'Settings' });
    expect(within(dialog).getByTestId('settings-account')).toHaveTextContent('me@example.com');
  });
});

describe('settings', () => {
  it("applies the account's theme on load and saves a change", async () => {
    vi.mocked(apiClient.getUserSettings).mockResolvedValue(doc({}, { appearance: { theme: 'light' } }));
    renderMenu();
    await waitFor(() => expect(document.documentElement.classList.contains('dark')).toBe(false));
    expect(apiClient.updateUserSettings).not.toHaveBeenCalled(); // applied, not echoed back

    const { user, dialog } = await openSettings();
    await user.click(within(within(dialog).getByTestId('settings-appearance')).getByRole('button', { name: 'Dark' }));
    expect(apiClient.updateUserSettings).toHaveBeenCalledWith({ appearance: { theme: 'dark' } });
    await waitFor(() => expect(document.documentElement.classList.contains('dark')).toBe(true));
  });

  it("keeps this browser's theme for a user who never saved settings", async () => {
    window.localStorage.setItem('quantlab-theme', 'light');
    vi.mocked(apiClient.getUserSettings).mockResolvedValue(doc({ updated_at: null }));
    renderMenu();
    await waitFor(() =>
      expect(apiClient.updateUserSettings).toHaveBeenCalledWith({ appearance: { theme: 'light' } }),
    );
  });

  it('saves the Market defaults and deletes a saved list', async () => {
    vi.mocked(apiClient.getUserSettings).mockResolvedValue(
      doc({}, {
        market: {
          default_data: 'historical',
          lists: [
            { name: 'Tech', symbols: ['AAPL.US'] },
            { name: 'Banks', symbols: ['JPM.US'] },
          ],
        },
      }),
    );
    renderMenu();
    const { user, dialog } = await openSettings();
    const market = within(dialog).getByTestId('settings-market');
    await user.click(within(market).getByRole('button', { name: 'Live intraday' }));
    expect(apiClient.updateUserSettings).toHaveBeenCalledWith({ market: { default_data: 'live' } });
    await user.click(within(market).getByRole('button', { name: 'Delete list Tech' }));
    expect(apiClient.updateUserSettings).toHaveBeenLastCalledWith({
      market: { lists: [{ name: 'Banks', symbols: ['JPM.US'] }] },
    });
  });

  it('says so when a change is refused, and puts the old value back', async () => {
    vi.mocked(apiClient.updateUserSettings).mockRejectedValue(new apiClient.ApiError(422, 'bad theme'));
    renderMenu();
    const { user, dialog } = await openSettings();
    const appearance = within(dialog).getByTestId('settings-appearance');
    await user.click(within(appearance).getByRole('button', { name: 'Light' }));
    expect(await within(dialog).findByTestId('settings-error')).toHaveTextContent('bad theme');
    expect(within(appearance).getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('IBKR credentials', () => {
  it('uploads the login, clears the password and shows the connection', async () => {
    vi.mocked(apiClient.putIbkrCredentials).mockResolvedValue(
      doc(
        { ibkr_connection: { state: 'logging_in', ib_username: 'my-ibkr', trading_mode: 'live', detail: 'Approve the IB Key notification on your phone.' } },
        { ibkr: { username: 'my-ibkr', trading_mode: 'live' } },
      ),
    );
    renderMenu();
    const { user, dialog } = await openSettings();
    const ibkr = within(dialog).getByTestId('settings-ibkr');
    await user.type(within(ibkr).getByLabelText('IBKR username'), 'my-ibkr');
    await user.selectOptions(within(ibkr).getByLabelText('Account'), 'live');
    await user.type(within(ibkr).getByLabelText('IBKR password'), 'hunter2');
    await user.click(within(ibkr).getByRole('button', { name: 'Save & connect' }));

    expect(apiClient.putIbkrCredentials).toHaveBeenCalledWith({
      username: 'my-ibkr',
      password: 'hunter2',
      trading_mode: 'live',
    });
    expect(within(ibkr).getByLabelText('IBKR password')).toHaveValue('');
    expect(await within(ibkr).findByTestId('settings-ibkr-status')).toHaveTextContent(/logging in/i);
    expect(within(ibkr).getByTestId('settings-ibkr-status')).toHaveTextContent(/IB Key/);
    expect(document.body.textContent).not.toContain('hunter2');
  });

  it('disconnects, and forgets the login only when asked', async () => {
    vi.mocked(apiClient.getUserSettings).mockResolvedValue(
      doc(
        { ibkr_connection: { state: 'connected', ib_username: 'my-ibkr', trading_mode: 'paper' } },
        { ibkr: { username: 'my-ibkr', trading_mode: 'paper' } },
      ),
    );
    vi.mocked(apiClient.deleteIbkrCredentials).mockImplementation(async (forget) =>
      doc({}, { ibkr: { username: forget ? null : 'my-ibkr', trading_mode: 'paper' } }),
    );
    renderMenu();
    const { user, dialog } = await openSettings();
    const ibkr = within(dialog).getByTestId('settings-ibkr');
    expect(within(ibkr).getByLabelText('IBKR username')).toHaveValue('my-ibkr');

    await user.click(within(ibkr).getByRole('button', { name: 'Disconnect' }));
    expect(apiClient.deleteIbkrCredentials).toHaveBeenCalledWith();
    await user.click(within(ibkr).getByRole('button', { name: 'Forget login' }));
    expect(apiClient.deleteIbkrCredentials).toHaveBeenLastCalledWith(true);
    await waitFor(() => expect(within(ibkr).getByLabelText('IBKR username')).toHaveValue(''));
  });

  it('says when this server has no live data', async () => {
    vi.mocked(apiClient.getUserSettings).mockResolvedValue(doc({ ibkr_connection: null }));
    renderMenu();
    const { dialog } = await openSettings();
    const ibkr = within(dialog).getByTestId('settings-ibkr');
    expect(within(ibkr).getByTestId('settings-ibkr-status')).toHaveTextContent(/not set up/i);
    expect(within(ibkr).getByRole('button', { name: 'Save & connect' })).toBeDisabled();
  });
});

describe('saved Market lists', () => {
  function Probe() {
    const { universes } = useCustomUniverses();
    return <p data-testid="lists">{universes.map((u) => u.name).join(',')}</p>;
  }

  it("move this browser's lists up to the account once, then read the account's", async () => {
    window.localStorage.setItem(
      'quantlab.market.universes',
      JSON.stringify([{ name: 'Old', symbols: ['AAPL.US'] }]),
    );
    renderMenu(<Probe />);
    await waitFor(() =>
      expect(apiClient.updateUserSettings).toHaveBeenCalledWith({
        market: { lists: [{ name: 'Old', symbols: ['AAPL.US'] }] },
      }),
    );
    await waitFor(() => expect(window.localStorage.getItem('quantlab.market.universes')).toBeNull());
    expect(screen.getByTestId('lists')).toHaveTextContent('Old');
  });
});
