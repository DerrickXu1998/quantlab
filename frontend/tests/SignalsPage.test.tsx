import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getPrices, listInstruments, listModels, listSignals } from '../src/api/client';
import { SignalsPage } from '../src/pages/SignalsPage';
import { ThemeProvider } from '../src/theme/ThemeProvider';
import { makeBar, makeInstrument, makeSignal } from './fixtures';

vi.mock('../src/api/client');

const mockedListSignals = vi.mocked(listSignals);
const mockedListInstruments = vi.mocked(listInstruments);
const mockedGetPrices = vi.mocked(getPrices);
const mockedListModels = vi.mocked(listModels);

// Mirrors how the page is composed in main.tsx — theme-aware children need the provider.
function renderPage() {
  return render(
    <ThemeProvider>
      <SignalsPage />
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mockedListModels.mockResolvedValue({ total: 0, items: [] });
});

describe('SignalsPage', () => {
  it('shows a loading state while requests are in flight', () => {
    mockedListInstruments.mockReturnValue(new Promise(() => {}));
    mockedListSignals.mockReturnValue(new Promise(() => {}));

    renderPage();
    // Scoped to the signals panel: the model catalog is legitimately also in a
    // loading state at this moment, so an unscoped query is now ambiguous.
    const panel = within(screen.getByTestId('panel-signals'));
    expect(panel.getByRole('status')).toHaveTextContent(/loading/i);
  });

  it('shows the signals with a total count matching the payload', async () => {
    mockedListInstruments.mockResolvedValue({ total: 1, items: [makeInstrument()] });
    mockedListSignals.mockResolvedValue({
      total: 2,
      items: [makeSignal(), makeSignal({ id: 2, symbol: 'ZZMEAN', direction: 'bearish' })],
    });

    renderPage();

    expect(await screen.findByTestId('signal-count')).toHaveTextContent('2');
    expect(screen.getByText('ZZTRND')).toBeInTheDocument();
    expect(screen.getByText('ZZMEAN')).toBeInTheDocument();
  });

  it('shows an explicit empty state when filters match nothing', async () => {
    mockedListInstruments.mockResolvedValue({ total: 1, items: [makeInstrument()] });
    mockedListSignals.mockResolvedValue({ total: 0, items: [] });

    renderPage();

    expect(await screen.findByTestId('empty-results')).toBeInTheDocument();
    expect(screen.queryByTestId('backend-unavailable')).not.toBeInTheDocument();
  });

  it('shows a backend-unavailable state, visually distinct from empty results, on failure', async () => {
    mockedListInstruments.mockResolvedValue({ total: 1, items: [makeInstrument()] });
    mockedListSignals.mockRejectedValue(new Error('connect ECONNREFUSED'));

    renderPage();

    expect(await screen.findByTestId('backend-unavailable')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-results')).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows the price-history context view with a marker when a row is selected', async () => {
    const user = userEvent.setup();
    mockedListInstruments.mockResolvedValue({ total: 1, items: [makeInstrument()] });
    mockedListSignals.mockResolvedValue({ total: 1, items: [makeSignal()] });
    mockedGetPrices.mockResolvedValue({
      total: 2,
      items: [makeBar(), makeBar({ date: '2024-03-15', close: 104 })],
    });

    renderPage();
    await user.click(await screen.findByText('ZZTRND'));

    expect(await screen.findByTestId('price-chart')).toBeInTheDocument();
    expect(screen.getByTestId('signal-marker')).toBeInTheDocument();
    expect(mockedGetPrices).toHaveBeenCalledWith('ZZTRND', undefined, undefined);
  });
});
