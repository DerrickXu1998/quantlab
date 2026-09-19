import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EMPTY_FILTERS, SignalFilters } from '../src/components/SignalFilters';
import { makeInstrument } from './fixtures';

function renderFilters(overrides: Partial<Parameters<typeof SignalFilters>[0]> = {}) {
  const props = {
    instruments: [
      makeInstrument(),
      makeInstrument({ symbol: 'ZZMEAN', name: 'Zeno Mean Reversion Co (synthetic)' }),
    ],
    value: { ...EMPTY_FILTERS },
    onChange: vi.fn(),
    ...overrides,
  };
  render(<SignalFilters {...props} />);
  return props;
}

describe('SignalFilters', () => {
  it('offers every instrument plus an "all" option and emits selection', async () => {
    const user = userEvent.setup();
    const props = renderFilters();

    const instrumentSelect = screen.getByLabelText(/instrument/i);
    expect(screen.getByRole('option', { name: /all instruments/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /ZZTRND/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /ZZMEAN/ })).toBeInTheDocument();

    await user.selectOptions(instrumentSelect, 'ZZTRND');
    expect(props.onChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, instrument: 'ZZTRND' });
  });

  it('offers the three signal rules and emits selection', async () => {
    const user = userEvent.setup();
    const props = renderFilters();

    const ruleSelect = screen.getByLabelText(/rule/i);
    for (const rule of ['sma-crossover', 'rsi-threshold', 'breakout-20d']) {
      expect(screen.getByRole('option', { name: rule })).toBeInTheDocument();
    }

    await user.selectOptions(ruleSelect, 'rsi-threshold');
    expect(props.onChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, signalType: 'rsi-threshold' });
  });

  it('emits direction via the toggle group', async () => {
    const user = userEvent.setup();
    const props = renderFilters();

    await user.click(screen.getByRole('radio', { name: /bearish/i }));
    expect(props.onChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, direction: 'bearish' });

    const propsAll = renderFilters({ value: { ...EMPTY_FILTERS, direction: 'bullish' } });
    await user.click(screen.getAllByRole('radio', { name: /^all$/i })[1]);
    expect(propsAll.onChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, direction: '' });
  });

  it('emits start and end dates', () => {
    const props = renderFilters();

    fireEvent.change(screen.getByLabelText(/start date/i), { target: { value: '2024-01-01' } });
    expect(props.onChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, startDate: '2024-01-01' });

    fireEvent.change(screen.getByLabelText(/end date/i), { target: { value: '2024-06-30' } });
    expect(props.onChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, endDate: '2024-06-30' });
  });

  it('emits date sort order', async () => {
    const user = userEvent.setup();
    const props = renderFilters();

    await user.selectOptions(screen.getByLabelText(/sort/i), 'date_asc');
    expect(props.onChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, sort: 'date_asc' });
  });

  it('reflects the controlled value', () => {
    renderFilters({
      value: {
        instrument: 'ZZMEAN',
        signalType: 'breakout-20d',
        direction: 'bullish',
        startDate: '2024-01-01',
        endDate: '2024-12-31',
        sort: 'date_asc',
      },
    });

    expect(screen.getByLabelText(/instrument/i)).toHaveValue('ZZMEAN');
    expect(screen.getByLabelText(/rule/i)).toHaveValue('breakout-20d');
    expect(screen.getByRole('radio', { name: /bullish/i })).toBeChecked();
    expect(screen.getByLabelText(/start date/i)).toHaveValue('2024-01-01');
    expect(screen.getByLabelText(/end date/i)).toHaveValue('2024-12-31');
    expect(screen.getByLabelText(/sort/i)).toHaveValue('date_asc');
  });
});
