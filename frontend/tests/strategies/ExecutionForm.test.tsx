import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import type { ExecutionConfig } from '../../src/api/types';
import { DEFAULT_EXECUTION } from '../../src/api/types';
import { ExecutionForm } from '../../src/strategies/ExecutionForm';

/**
 * Driven as the builder drives it — controlled, with the parent owning the
 * config — because half of what is under test is what a change to one field
 * does to the visibility of another.
 */
function Harness({ initial = DEFAULT_EXECUTION }: { initial?: ExecutionConfig }) {
  const [value, setValue] = useState<ExecutionConfig>(initial);
  return (
    <>
      <ExecutionForm value={value} onChange={setValue} />
      <pre data-testid="config">{JSON.stringify(value)}</pre>
    </>
  );
}

function config(): ExecutionConfig {
  return JSON.parse(screen.getByTestId('config').textContent ?? '{}') as ExecutionConfig;
}

describe('ExecutionForm', () => {
  it('covers §4 in four named groups rather than one wall of inputs', () => {
    render(<Harness />);

    for (const group of [
      /capital & sizing/i,
      /entry & exit timing/i,
      /risk controls/i,
      /costs/i,
    ]) {
      expect(screen.getByRole('group', { name: group })).toBeInTheDocument();
    }
  });

  it('gives every control a line saying what it does to the result', () => {
    render(<Harness />);

    const stop = screen.getByLabelText(/stop loss/i);
    const describedBy = stop.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy as string)).toHaveTextContent(
      /exit once price has moved this far against the entry/i,
    );
  });

  it('hides the sizing value under equal weight, which does not read it', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    expect(screen.queryByTestId('execution-sizing-value')).not.toBeInTheDocument();

    await person.selectOptions(screen.getByLabelText(/position sizing/i), 'fixed_fraction');

    const field = screen.getByTestId('execution-sizing-value');
    expect(field).toBeInTheDocument();
    expect(screen.getByLabelText(/sizing value/i)).toBe(field);
  });

  it('relabels the sizing value for the mode that reads it as cash', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    await person.selectOptions(screen.getByLabelText(/position sizing/i), 'fixed_notional');

    expect(screen.getByLabelText(/cash per trade/i)).toBeInTheDocument();
    expect(
      document.getElementById(
        screen.getByLabelText(/cash per trade/i).getAttribute('aria-describedby') as string,
      ),
    ).toHaveTextContent(/cash amount put into each position/i);
  });

  it('clears a sizing value that the newly chosen mode would ignore', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    await person.selectOptions(screen.getByLabelText(/position sizing/i), 'fixed_fraction');
    expect(config().sizing_value).not.toBeNull();

    await person.selectOptions(screen.getByLabelText(/position sizing/i), 'equal_weight');

    // A number left behind in a field nothing reads would be recorded on the
    // run as if it had done something.
    expect(config().sizing_value).toBeNull();
  });

  it('asks for the ATR period only once there is an ATR stop to measure', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    expect(screen.queryByTestId('execution-atr-period')).not.toBeInTheDocument();

    await person.type(screen.getByLabelText(/atr stop multiple/i), '2');

    expect(screen.getByTestId('execution-atr-period')).toHaveValue(14);
    expect(config().atr_stop_multiple).toBe(2);
  });

  it('takes percentages on screen and stores the fractions the API wants', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    await person.type(screen.getByLabelText(/stop loss/i), '5');
    await person.type(screen.getByLabelText(/take profit/i), '12.5');

    expect(config().stop_loss_pct).toBe(0.05);
    expect(config().take_profit_pct).toBe(0.125);
  });

  it('treats a blank protective field as off, never as zero', async () => {
    const person = userEvent.setup();
    render(<Harness initial={{ ...DEFAULT_EXECUTION, stop_loss_pct: 0.05 }} />);

    expect(screen.getByLabelText(/stop loss/i)).toHaveValue(5);

    await person.clear(screen.getByLabelText(/stop loss/i));

    // A 0% stop would exit the instant a position opened.
    expect(config().stop_loss_pct).toBeNull();
  });

  it('treats a blank max positions as no cap', async () => {
    const person = userEvent.setup();
    render(<Harness initial={{ ...DEFAULT_EXECUTION, max_positions: 4 }} />);

    await person.clear(screen.getByLabelText(/max positions/i));

    expect(config().max_positions).toBeNull();
  });

  it('carries the resolution order, because it changes what the numbers mean', () => {
    render(<Harness />);

    const explainer = screen.getByTestId('resolution-order');
    expect(explainer).toHaveTextContent(/protective exits/i);
    expect(explainer).toHaveTextContent(/stop loss → trailing stop → take profit → max holding/i);
    expect(explainer).toHaveTextContent(/signal exits, once min holding days has elapsed/i);
    // The pessimistic reading is stated, not implied.
    expect(explainer).toHaveTextContent(/resolve to the stop/i);
    expect(explainer).toHaveTextContent(/gap through the level fills at the open/i);
  });

  it('explains what each fill timing costs in realism as it is chosen', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    const timing = screen.getByLabelText(/fill timing/i);
    expect(document.getElementById(timing.getAttribute('aria-describedby') as string))
      .toHaveTextContent(/optimistic/i);

    await person.selectOptions(timing, 'next_open');

    expect(document.getElementById(timing.getAttribute('aria-describedby') as string))
      .toHaveTextContent(/first price you could genuinely have traded/i);
    expect(config().fill_timing).toBe('next_open');
  });

  it('carries costs through as basis points on both sides', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    await person.clear(screen.getByLabelText(/commission/i));
    await person.type(screen.getByLabelText(/commission/i), '5');
    await person.clear(screen.getByLabelText(/slippage/i));
    await person.type(screen.getByLabelText(/slippage/i), '2');

    expect(config().commission_bps).toBe(5);
    expect(config().slippage_bps).toBe(2);
  });

  it('exposes allow shorts as a real checkbox with its consequence spelled out', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    const shorts = screen.getByLabelText(/allow shorts/i);
    expect(shorts).not.toBeChecked();

    await person.click(shorts);

    expect(config().allow_shorts).toBe(true);
    expect(
      document.getElementById(shorts.getAttribute('aria-describedby') as string),
    ).toHaveTextContent(/bearish entry opens a short/i);
  });
});
