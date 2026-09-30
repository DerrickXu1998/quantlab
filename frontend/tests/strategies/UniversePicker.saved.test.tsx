import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../src/api/client';
import { UniversesProvider } from '../../src/api/UniversesProvider';
import type { Instrument } from '../../src/api/client';
import { UniversePicker, latestSnapshots } from '../../src/strategies/UniversePicker';

const instruments = [
  { symbol: 'AAPL.US', name: 'Apple', currency: 'USD' },
  { symbol: 'MSFT.US', name: 'Microsoft', currency: 'USD' },
  { symbol: 'VOD.LON', name: 'Vodafone', currency: 'GBP' },
] as unknown as Instrument[];

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    listUniverses: vi.fn(),
    createUniverse: vi.fn(),
    getUniverseMembers: vi.fn(),
  };
});

beforeEach(() => {
  vi.mocked(apiClient.listUniverses).mockResolvedValue({
    total: 3,
    items: [
      { name: 'my-tech', as_of: '2026-09-29', size: 3 },
      { name: 'my-tech', as_of: '2026-09-01', size: 1 },
      { name: 'uk-core', as_of: '2026-09-20', size: 1 },
    ],
  });
});

let current: string[] = [];
function Harness({ initial = [] as string[] }) {
  const [selected, setSelected] = useState(initial);
  current = selected;
  return (
    <UniversesProvider>
      <UniversePicker instruments={instruments} selected={selected} onChange={setSelected} />
    </UniversesProvider>
  );
}

describe('latestSnapshots', () => {
  it('keeps one entry per universe, its newest snapshot', () => {
    const latest = latestSnapshots([
      { name: 'b', as_of: '2026-01-01', size: 1 },
      { name: 'a', as_of: '2026-01-01', size: 1 },
      { name: 'b', as_of: '2026-03-01', size: 2 },
    ]);
    expect(latest).toEqual([
      { name: 'a', as_of: '2026-01-01', size: 1 },
      { name: 'b', as_of: '2026-03-01', size: 2 },
    ]);
  });
});

describe('UniversePicker, saved universes', () => {
  it('offers each saved universe once, and loading one replaces the selection', async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.getUniverseMembers).mockResolvedValue({
      name: 'my-tech',
      as_of: '2026-09-29',
      symbols: ['AAPL.US', 'MSFT.US', 'GONE.US'],
    });
    render(<Harness initial={['VOD.LON']} />);

    const picker = await screen.findByLabelText('Saved universes');
    const options = [...picker.querySelectorAll('option')].map((o) => o.textContent);
    expect(options).toEqual([
      'Load a saved universe…',
      'my-tech · 3 · 2026-09-29',
      'uk-core · 1 · 2026-09-20',
    ]);

    await user.selectOptions(picker, 'my-tech');

    // Asked for exactly the snapshot listed, not "whatever is newest today".
    expect(apiClient.getUniverseMembers).toHaveBeenCalledWith('my-tech', '2026-09-29');
    expect(await screen.findByTestId('saved-universe-notice')).toHaveTextContent(
      'Loaded "my-tech" as of 2026-09-29: 2 tickers, 1 not in this catalogue left out.',
    );
    expect(current).toEqual(['AAPL.US', 'MSFT.US']);
  });

  it('says so when a saved universe cannot be loaded', async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.getUniverseMembers).mockRejectedValue(
      new apiClient.ApiError(404, "no universe 'uk-core' with a snapshot on or before 2026-09-20"),
    );
    render(<Harness />);

    await user.selectOptions(await screen.findByLabelText('Saved universes'), 'uk-core');

    expect(await screen.findByRole('alert')).toHaveTextContent(/no universe 'uk-core'/);
  });

  it('shows nothing extra when no universe has been saved', async () => {
    vi.mocked(apiClient.listUniverses).mockResolvedValue({ total: 0, items: [] });
    render(<Harness />);
    await screen.findByRole('group', { name: /universe presets/i });
    expect(screen.queryByLabelText('Saved universes')).not.toBeInTheDocument();
  });
});
