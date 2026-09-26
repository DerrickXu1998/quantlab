import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import type { Instrument } from '../../src/api/client';
import { UniversePicker } from '../../src/strategies/UniversePicker';

const instruments = [
  { symbol: 'AAPL.US', name: 'Apple', currency: 'USD' },
  { symbol: 'MSFT.US', name: 'Microsoft', currency: 'USD' },
  { symbol: 'BP.LON', name: 'BP', currency: 'GBP' },
  { symbol: 'VOD.LON', name: 'Vodafone', currency: 'GBP' },
  { symbol: 'DGS10.FRED', name: '10-year Treasury yield', currency: 'USD' },
  { symbol: 'BANKRATE.BOE', name: 'Bank Rate', currency: 'GBP' },
] as unknown as Instrument[];

function Harness({ initial = [] as string[] }) {
  const [selected, setSelected] = useState(initial);
  return <UniversePicker instruments={instruments} selected={selected} onChange={setSelected} />;
}

function selectedSymbols(): string[] {
  const list = screen.queryByRole('list', { name: /selected tickers/i });
  if (!list) return [];
  return within(list)
    .getAllByRole('button', { name: /^remove /i })
    .map((button) => button.textContent ?? '');
}

describe('UniversePicker', () => {
  it('fills a universe from a market preset, leaving macro series out', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole('button', { name: /all us\s*2/i }));
    expect(selectedSymbols()).toEqual(['AAPL.US', 'MSFT.US']);

    // A strategy cannot trade the Bank Rate: "Everything" is the four equities.
    await user.click(screen.getByRole('button', { name: /everything\s*4/i }));
    expect(selectedSymbols()).toHaveLength(4);
    expect(selectedSymbols().join(' ')).not.toMatch(/FRED|BOE/);
  });

  it('adds the best match on Enter, by ticker or by name', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const search = screen.getByLabelText(/add tickers/i);

    await user.type(search, 'vodafone{Enter}');
    await user.type(search, 'ms{Enter}');

    expect(selectedSymbols()).toEqual(['VOD.LON', 'MSFT.US']);
    expect(search).toHaveValue('');
  });

  it('never offers macro series or a ticker already chosen', async () => {
    const user = userEvent.setup();
    render(<Harness initial={['AAPL.US']} />);

    await user.type(screen.getByLabelText(/add tickers/i), 'a');

    const matches = screen.getByRole('list', { name: /matching tickers/i });
    expect(within(matches).queryByText('AAPL.US')).not.toBeInTheDocument();
    expect(within(matches).queryByText('BANKRATE.BOE')).not.toBeInTheDocument();
  });

  it('removes one ticker, or clears them all', async () => {
    const user = userEvent.setup();
    render(<Harness initial={['AAPL.US', 'BP.LON', 'VOD.LON']} />);
    expect(screen.getByTestId('universe-count')).toHaveTextContent(/3 tickers/i);

    await user.click(screen.getByRole('button', { name: 'Remove BP.LON' }));
    expect(selectedSymbols()).toEqual(['AAPL.US', 'VOD.LON']);

    await user.click(screen.getByRole('button', { name: /^clear$/i }));
    expect(selectedSymbols()).toEqual([]);
    expect(screen.getByTestId('universe-count')).toHaveTextContent(/0 tickers/i);
  });
});
