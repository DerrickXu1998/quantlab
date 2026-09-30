import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  RangeControl,
  rangeStart,
  shiftMonths,
} from '../../../src/research/company/RangeControl';

describe('shiftMonths', () => {
  it('moves back whole months and years', () => {
    expect(shiftMonths('2026-09-30', 1)).toBe('2026-08-30');
    expect(shiftMonths('2026-09-30', 12)).toBe('2025-09-30');
    expect(shiftMonths('2026-01-15', 3)).toBe('2025-10-15');
  });

  it('clamps to the end of a shorter month rather than rolling over', () => {
    expect(shiftMonths('2026-03-31', 1)).toBe('2026-02-28');
    expect(shiftMonths('2024-03-31', 1)).toBe('2024-02-29');
  });
});

describe('rangeStart', () => {
  it('counts back from the as-of date, and Max means the whole history', () => {
    expect(rangeStart('2026-09-30', '6M')).toBe('2026-03-30');
    expect(rangeStart('2026-09-30', '10Y')).toBe('2016-09-30');
    expect(rangeStart('2026-09-30', 'MAX')).toBeNull();
  });
});

describe('RangeControl', () => {
  it('marks the chosen range and states the window it resolves to', async () => {
    const onChange = vi.fn();
    render(<RangeControl value="1Y" onChange={onChange} asOf="2026-09-30" />);

    expect(screen.getByRole('button', { name: '1Y' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Chart and backtests cover 2025-09-30 → 2026-09-30.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '3M' }));
    expect(onChange).toHaveBeenCalledWith('3M');
  });
});
