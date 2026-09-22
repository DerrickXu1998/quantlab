import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AsOfControl, presetsFor, shiftYears } from '../../../src/research/company/AsOfControl';

describe('shiftYears', () => {
  it('moves whole years back and stays in ISO', () => {
    expect(shiftYears('2026-09-21', 1)).toBe('2025-09-21');
    expect(shiftYears('2026-09-21', 10)).toBe('2016-09-21');
  });

  it('does not fall off the end of February', () => {
    expect(shiftYears('2024-02-29', 1)).toBe('2023-03-01');
  });
});

describe('presetsFor', () => {
  it('offers today and three round steps back', () => {
    expect(presetsFor('2026-09-21')).toEqual([
      { label: 'Today', value: '2026-09-21' },
      { label: '1Y ago', value: '2025-09-21' },
      { label: '5Y ago', value: '2021-09-21' },
      { label: '10Y ago', value: '2016-09-21' },
    ]);
  });
});

describe('AsOfControl', () => {
  it('states what the date does, which is the point of the screen', () => {
    render(<AsOfControl value="2026-09-21" onChange={vi.fn()} today="2026-09-21" />);
    expect(screen.getByText(/nothing filed after it is shown/i)).toBeInTheDocument();
  });

  it('moves the cut back on a preset', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<AsOfControl value="2026-09-21" onChange={onChange} today="2026-09-21" />);

    await user.click(screen.getByRole('button', { name: '5Y ago' }));

    expect(onChange).toHaveBeenCalledWith('2021-09-21');
  });

  it('marks the preset that is currently in force', () => {
    render(<AsOfControl value="2025-09-21" onChange={vi.fn()} today="2026-09-21" />);
    expect(screen.getByRole('button', { name: '1Y ago' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Today' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('never offers a date in the future', () => {
    render(<AsOfControl value="2026-09-21" onChange={vi.fn()} today="2026-09-21" />);
    expect(screen.getByLabelText(/as of/i)).toHaveAttribute('max', '2026-09-21');
  });

  it('says so out loud when the server resolved to a different date', () => {
    // A silent substitution is precisely the class of quiet wrongness this
    // screen exists to expose, so a loud one is the only acceptable kind.
    render(
      <AsOfControl
        value="2024-06-30"
        onChange={vi.fn()}
        today="2026-09-21"
        resolved="2024-06-28"
      />,
    );
    expect(
      screen.getByText(/requested 2024-06-30; the server resolved to 2024-06-28/i),
    ).toBeInTheDocument();
  });

  it('stays quiet when the server agreed with the request', () => {
    render(
      <AsOfControl
        value="2024-06-30"
        onChange={vi.fn()}
        today="2026-09-21"
        resolved="2024-06-30"
      />,
    );
    expect(screen.queryByText(/the server resolved to/i)).not.toBeInTheDocument();
  });
});
