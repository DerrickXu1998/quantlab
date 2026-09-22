import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  RENDER_LIMIT,
  SymbolPicker,
  matchInstruments,
} from '../../../src/research/company/SymbolPicker';
import { makeInstrument } from '../../fixtures';

const catalogue = [
  makeInstrument({ symbol: 'CAT', name: 'Caterpillar Inc.' }),
  makeInstrument({ symbol: 'CATY', name: 'Cathay General Bancorp' }),
  makeInstrument({ symbol: 'DE', name: 'Deere & Company' }),
  makeInstrument({ symbol: 'TSCO', name: 'Tractor Supply Company' }),
];

function renderPicker(props: Partial<React.ComponentProps<typeof SymbolPicker>> = {}) {
  const onSelect = vi.fn();
  render(
    <SymbolPicker
      instruments={catalogue}
      status="ready"
      message={null}
      selected={null}
      onSelect={onSelect}
      {...props}
    />,
  );
  return { onSelect };
}

describe('matchInstruments', () => {
  it('ranks an exact symbol above a name that merely contains the letters', () => {
    // Someone who types CAT means Caterpillar, not Tractor Supply Company.
    const matched = matchInstruments(catalogue, 'cat');
    expect(matched.map((instrument) => instrument.symbol)).toEqual(['CAT', 'CATY']);
  });

  it('searches company names, so a half-remembered name still finds the ticker', () => {
    expect(matchInstruments(catalogue, 'deere').map((i) => i.symbol)).toEqual(['DE']);
    // A name-only match still lands, and lands below the symbol matches.
    expect(matchInstruments(catalogue, 'company').map((i) => i.symbol)).toEqual(['DE', 'TSCO']);
  });

  it('is case- and whitespace-insensitive', () => {
    expect(matchInstruments(catalogue, '  CaTeRpillar ').map((i) => i.symbol)).toEqual(['CAT']);
  });

  it('lists the whole catalogue alphabetically when nothing has been typed', () => {
    expect(matchInstruments(catalogue, '').map((i) => i.symbol)).toEqual([
      'CAT',
      'CATY',
      'DE',
      'TSCO',
    ]);
  });

  it('returns nothing for a symbol that is not catalogued', () => {
    expect(matchInstruments(catalogue, 'zzzz')).toEqual([]);
  });
});

describe('SymbolPicker', () => {
  it('states the first action, with the size of the catalogue', async () => {
    renderPicker();
    const input = screen.getByRole('combobox');
    expect(input).toHaveAttribute('placeholder', expect.stringMatching(/search 4 instruments/i));
    expect(screen.getByText(/type a ticker or part of a company name/i)).toBeInTheDocument();
  });

  it('selects by keyboard: type, arrow down, enter', async () => {
    const user = userEvent.setup();
    const { onSelect } = renderPicker();

    await user.click(screen.getByRole('combobox'));
    await user.keyboard('cat');
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{Enter}');

    expect(onSelect).toHaveBeenCalledWith('CATY');
  });

  it('selects the best match on Enter without arrowing', async () => {
    const user = userEvent.setup();
    const { onSelect } = renderPicker();

    await user.click(screen.getByRole('combobox'));
    await user.keyboard('deere{Enter}');

    expect(onSelect).toHaveBeenCalledWith('DE');
  });

  it('selects by click', async () => {
    const user = userEvent.setup();
    const { onSelect } = renderPicker();

    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByRole('option', { name: /Caterpillar/ }));

    expect(onSelect).toHaveBeenCalledWith('CAT');
  });

  it('says the name is not in the catalogue rather than showing an empty list', async () => {
    const user = userEvent.setup();
    renderPicker();

    await user.click(screen.getByRole('combobox'));
    await user.keyboard('zzzz');

    expect(screen.getByTestId('symbol-picker-no-match')).toHaveTextContent(
      /no instrument matches/i,
    );
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('caps the rendered rows and says how many matched, so 644 names do not jank', async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 644 }, (_, index) =>
      makeInstrument({ symbol: `SY${index}`, name: `Synthetic ${index}` }),
    );
    render(
      <SymbolPicker
        instruments={many}
        status="ready"
        message={null}
        selected={null}
        onSelect={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('combobox'));

    expect(screen.getAllByRole('option')).toHaveLength(RENDER_LIMIT);
    expect(screen.getByText(new RegExp(`${RENDER_LIMIT} of 644 matches`))).toBeInTheDocument();
  });

  it('closes on Escape', async () => {
    const user = userEvent.setup();
    renderPicker();

    await user.click(screen.getByRole('combobox'));
    expect(screen.getByRole('listbox')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('names the selected company so a reader can see they landed on the right one', () => {
    renderPicker({ selected: 'CAT' });
    expect(screen.getByText(/showing caterpillar inc\./i)).toBeInTheDocument();
  });

  it('distinguishes a catalogue that is not served from one that failed', () => {
    const { unmount } = render(
      <SymbolPicker
        instruments={[]}
        status="unsupported"
        message={null}
        selected={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/does not serve \/instruments/i)).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toBeDisabled();
    unmount();

    render(
      <SymbolPicker
        instruments={[]}
        status="error"
        message="Backend unreachable at /api/v1"
        selected={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/could not be read: backend unreachable/i)).toBeInTheDocument();
  });

  it('says the catalogue is loading in words, not as a bare spinner', () => {
    renderPicker({ status: 'loading', instruments: [] });
    expect(screen.getByText(/reading the catalogue of instruments/i)).toBeInTheDocument();
  });
});
