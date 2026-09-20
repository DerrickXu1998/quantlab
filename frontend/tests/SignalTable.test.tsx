import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SignalTable } from '../src/components/SignalTable';
import { makeSignal } from './fixtures';

function renderTable(overrides: Partial<Parameters<typeof SignalTable>[0]> = {}) {
  const props = {
    signals: [
      makeSignal(),
      makeSignal({
        id: 2,
        symbol: 'ZZMEAN',
        date: '2024-02-01',
        rule_name: 'rsi-threshold',
        direction: 'bearish',
        trigger_values: { rsi: 74.5 },
      }),
    ],
    total: 42,
    selectedId: null,
    page: 0,
    pageSize: 50,
    onPageChange: vi.fn(),
    onSelect: vi.fn(),
    ...overrides,
  };
  render(<SignalTable {...props} />);
  return props;
}

describe('SignalTable', () => {
  it('renders a row per signal with symbol, date, rule name+version, direction badge and trigger values', () => {
    renderTable();

    expect(screen.getByText('ZZTRND')).toBeInTheDocument();
    expect(screen.getByText('2024-03-15')).toBeInTheDocument();
    expect(screen.getByText('sma-crossover v1.0.0')).toBeInTheDocument();
    expect(screen.getByText('bullish')).toBeInTheDocument();
    expect(screen.getByText(/sma_fast=101\.2/)).toBeInTheDocument();

    expect(screen.getByText('rsi-threshold v1.0.0')).toBeInTheDocument();
    expect(screen.getByText('bearish')).toBeInTheDocument();
    expect(screen.getByText(/rsi=74\.5/)).toBeInTheDocument();
  });

  it('shows the total count from the payload, not the number of rendered rows', () => {
    renderTable({ total: 42 });
    expect(screen.getByTestId('signal-count')).toHaveTextContent('42');
  });

  it('renders an explicit empty state when items are empty', () => {
    renderTable({ signals: [], total: 0 });
    expect(screen.getByTestId('empty-results')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('calls onSelect with the signal when its row is clicked', async () => {
    const user = userEvent.setup();
    const props = renderTable();
    await user.click(screen.getByText('ZZTRND'));
    expect(props.onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, symbol: 'ZZTRND' }),
    );
  });

  it('emits page changes and disables next on the last page', async () => {
    const user = userEvent.setup();
    const props = renderTable({ total: 120, page: 0, pageSize: 50 });
    await user.click(screen.getByRole('button', { name: /next/i }));
    expect(props.onPageChange).toHaveBeenCalledWith(1);

    renderTable({ total: 120, page: 2, pageSize: 50 });
    expect(screen.getAllByRole('button', { name: /next/i })[1]).toBeDisabled();
  });
});

describe('SignalTable re-run handoff', () => {
  afterEach(() => {
    window.location.hash = '';
  });

  it('"Re-run" deep-links Strategies with the model and parameters prefilled', async () => {
    const user = userEvent.setup();
    renderTable();

    // The row click selects; the action navigates.
    await user.click(screen.getAllByRole('button', { name: /re-run/i })[0]);

    expect(window.location.hash).toBe(
      '#/strategies?model=sma-crossover&version=1.0.0&p_fast=20&p_slow=50',
    );
  });

  it('does not select the row when the re-run action is used', async () => {
    const user = userEvent.setup();
    const props = renderTable();

    await user.click(screen.getAllByRole('button', { name: /re-run/i })[0]);

    expect(props.onSelect).not.toHaveBeenCalled();
  });
});
