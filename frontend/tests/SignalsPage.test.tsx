import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getPrices, listInstruments, listSignals } from '../src/api/client';
import { SignalsPage } from '../src/pages/SignalsPage';
import { makeBar, makeInstrument, makeSignal } from './fixtures';

vi.mock('../src/api/client');

const mockedListSignals = vi.mocked(listSignals);
const mockedListInstruments = vi.mocked(listInstruments);
const mockedGetPrices = vi.mocked(getPrices);

beforeEach(() => {
  vi.resetAllMocks();
});

describe('SignalsPage', () => {
  it('shows a loading state while requests are in flight', () => {
    mockedListInstruments.mockReturnValue(new Promise(() => {}));
    mockedListSignals.mockReturnValue(new Promise(() => {}));

    render(<SignalsPage />);
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i);
  });

  it('shows the signals with a total count matching the payload', async () => {
    mockedListInstruments.mockResolvedValue({ total: 1, items: [makeInstrument()] });
    mockedListSignals.mockResolvedValue({
      total: 2,
      items: [makeSignal(), makeSignal({ id: 2, symbol: 'ZZMEAN', direction: 'bearish' })],
    });

    render(<SignalsPage />);

    expect(await screen.findByTestId('signal-count')).toHaveTextContent('2');
    expect(screen.getByText('ZZTRND')).toBeInTheDocument();
    expect(screen.getByText('ZZMEAN')).toBeInTheDocument();
  });

  it('shows an explicit empty state when filters match nothing', async () => {
    mockedListInstruments.mockResolvedValue({ total: 1, items: [makeInstrument()] });
    mockedListSignals.mockResolvedValue({ total: 0, items: [] });

    render(<SignalsPage />);

    expect(await screen.findByTestId('empty-results')).toBeInTheDocument();
    expect(screen.queryByTestId('backend-unavailable')).not.toBeInTheDocument();
  });

  it('shows a backend-unavailable state, visually distinct from empty results, on failure', async () => {
    mockedListInstruments.mockResolvedValue({ total: 1, items: [makeInstrument()] });
    mockedListSignals.mockRejectedValue(new Error('connect ECONNREFUSED'));

    render(<SignalsPage />);

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

    render(<SignalsPage />);
    await user.click(await screen.findByText('ZZTRND'));

    expect(await screen.findByTestId('price-chart')).toBeInTheDocument();
    expect(screen.getByTestId('signal-marker')).toBeInTheDocument();
    expect(mockedGetPrices).toHaveBeenCalledWith('ZZTRND', undefined, undefined);
  });
});
