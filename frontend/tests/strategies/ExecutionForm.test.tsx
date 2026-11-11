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
  it('backtests at daily accuracy unless minute is chosen, and gates VWAP on it', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const accuracy = screen.getByLabelText(/execution accuracy/i);
    const fills = screen.getByLabelText(/fill timing/i);

    expect(accuracy).toHaveValue('daily');
    expect(screen.getByRole('option', { name: /VWAP \(minute bars\)/ })).toBeDisabled();

    await user.selectOptions(accuracy, 'minute');
    await user.selectOptions(fills, 'next_vwap');
    expect(config()).toMatchObject({ intraday_resolution: 'minute', fill_timing: 'next_vwap' });

    // Back to daily: VWAP has no daily form, so it falls back to its stand-in.
    await user.selectOptions(accuracy, 'daily');
    expect(config()).toMatchObject({ intraday_resolution: 'daily', fill_timing: 'next_typical' });
  });

  it('hides execution accuracy on intraday bars and rules out VWAP', () => {
    render(<Harness initial={{ ...DEFAULT_EXECUTION, bar_frequency: '5m' }} />);
    // Intraday bars already step through the session: nothing to choose.
    expect(screen.queryByLabelText(/execution accuracy/i)).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: /VWAP \(minute bars\)/ })).toBeDisabled();
  });

  it('offers execution accuracy on daily bars', () => {
    render(<Harness />);
    expect(screen.getByLabelText(/execution accuracy/i)).toBeEnabled();
  });

  it('states holding periods and cooldowns in trading days, never bars', () => {
    render(<Harness initial={{ ...DEFAULT_EXECUTION, bar_frequency: '5m' }} />);
    for (const field of [/min holding days/i, /max holding days/i, /cooldown/i]) {
      // The unit printed beside the input.
      const unit = screen.getByLabelText(field).parentElement;
      expect(unit).toHaveTextContent(/^days$/);
      const help = document.getElementById(
        screen.getByLabelText(field).getAttribute('aria-describedby') ?? '',
      );
      expect(help).toHaveTextContent(/trading days/i);
    }
  });

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
    expect(timing).toHaveValue('next_open');
    expect(document.getElementById(timing.getAttribute('aria-describedby') as string))
      .toHaveTextContent(/first price you could genuinely have traded/i);

    await person.selectOptions(timing, 'signal_close');
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

  it('applies cost presets and identifies custom values', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    const profile = screen.getByLabelText(/cost profile/i);
    expect(profile).toHaveValue('base');
    expect(config()).toMatchObject({ commission_bps: 1, slippage_bps: 5 });

    await person.selectOptions(profile, 'stressed');
    expect(config()).toMatchObject({ commission_bps: 2, slippage_bps: 20 });

    await person.selectOptions(profile, 'idealized');
    expect(config()).toMatchObject({ commission_bps: 0, slippage_bps: 0 });

    await person.clear(screen.getByLabelText(/commission/i));
    await person.type(screen.getByLabelText(/commission/i), '3');
    expect(profile).toHaveValue('custom');
  });

  it('configures volume participation and signal-order expiry', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    const participation = screen.getByLabelText(/max volume participation/i);
    expect(participation).toHaveValue(1);
    expect(config()).toMatchObject({ max_volume_participation: 0.01, order_expiry_days: 5 });

    await person.clear(participation);
    await person.type(participation, '2.5');
    await person.clear(screen.getByLabelText(/order expiry/i));
    await person.type(screen.getByLabelText(/order expiry/i), '3');
    expect(config()).toMatchObject({ max_volume_participation: 0.025, order_expiry_days: 3 });

    await person.clear(participation);
    expect(config().max_volume_participation).toBeNull();
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

describe('ExecutionForm: portfolio allocation', () => {
  const sizing = () => screen.getByLabelText(/position sizing/i);
  const allocationGroup = () => screen.queryByRole('group', { name: /^portfolio allocation$/i });

  it('groups the shared-capital modes apart from the independent ones', () => {
    render(<Harness />);
    const groups = sizing().querySelectorAll('optgroup');
    expect([...groups].map((group) => group.label)).toEqual([
      'Independent sizing',
      'Portfolio allocation (shared capital)',
    ]);
    expect([...groups[1].querySelectorAll('option')].map((option) => option.value)).toEqual([
      'equal_active',
      'signal_strength',
      'signal_inverse_volatility',
    ]);
  });

  it('shows the allocation subsection only under an allocation mode, with its explainer', async () => {
    const person = userEvent.setup();
    render(<Harness />);
    expect(allocationGroup()).not.toBeInTheDocument();

    await person.selectOptions(sizing(), 'signal_strength');

    expect(allocationGroup()).toBeInTheDocument();
    const explainer = screen.getByTestId('allocation-explainer');
    expect(explainer).toHaveTextContent(/share one pool of capital/i);
    expect(explainer).toHaveTextContent(/trim positions in others/i);
    expect(explainer).toHaveTextContent(/own sleeve/i);
    // The targets set the size: there is no sizing value to enter.
    expect(screen.queryByTestId('execution-sizing-value')).not.toBeInTheDocument();
    // Unset fields stay unset; the backend resolves their defaults.
    expect(screen.getByLabelText(/target exposure/i)).toHaveValue(null);
    expect(screen.getByLabelText(/^rebalance$/i)).toHaveValue('on_signal');
    expect(config()).not.toHaveProperty('target_exposure');
    // Only inverse volatility reads a volatility lookback.
    expect(screen.queryByTestId('execution-volatility-lookback')).not.toBeInTheDocument();

    await person.selectOptions(sizing(), 'signal_inverse_volatility');
    expect(screen.getByTestId('execution-volatility-lookback')).toHaveValue(14);
  });

  it('takes percentages on screen and stores fractions', async () => {
    const person = userEvent.setup();
    render(<Harness />);
    await person.selectOptions(sizing(), 'equal_active');

    await person.type(screen.getByLabelText(/target exposure/i), '80');
    await person.type(screen.getByLabelText(/min allocation score/i), '50');
    await person.type(screen.getByLabelText(/rebalance threshold/i), '2.5');
    await person.type(screen.getByLabelText(/max turnover/i), '150');
    await person.selectOptions(screen.getByLabelText(/^rebalance$/i), 'weekly');

    expect(config()).toMatchObject({
      position_sizing: 'equal_active',
      sizing_value: null,
      target_exposure: 0.8,
      min_allocation_score: 0.5,
      rebalance_threshold: 0.025,
      max_turnover: 1.5,
      rebalance_frequency: 'weekly',
    });

    // Blank is the default, never zero.
    await person.clear(screen.getByLabelText(/max turnover/i));
    expect(config().max_turnover).toBeNull();
  });

  it('clears a stale sizing value and the allocation fields when the mode changes', async () => {
    const person = userEvent.setup();
    render(<Harness />);

    await person.selectOptions(sizing(), 'fixed_fraction');
    expect(config().sizing_value).toBe(0.2);

    await person.selectOptions(sizing(), 'signal_strength');
    expect(config().sizing_value).toBeNull();
    await person.type(screen.getByLabelText(/target exposure/i), '60');

    // Between allocation modes the shared settings carry over.
    await person.selectOptions(sizing(), 'equal_active');
    expect(config().target_exposure).toBe(0.6);

    // A legacy mode refuses every allocation field, so none is left behind.
    await person.selectOptions(sizing(), 'equal_weight');
    const legacy = config();
    for (const field of [
      'target_exposure',
      'min_allocation_score',
      'rebalance_frequency',
      'rebalance_threshold',
      'max_turnover',
    ]) {
      expect(legacy).not.toHaveProperty(field);
    }
    expect(allocationGroup()).not.toBeInTheDocument();
  });

  it('does not read a cash amount as a fraction', async () => {
    const person = userEvent.setup();
    render(
      <Harness
        initial={{ ...DEFAULT_EXECUTION, position_sizing: 'fixed_notional', sizing_value: 25000 }}
      />,
    );

    await person.selectOptions(sizing(), 'fixed_fraction');
    expect(config().sizing_value).toBe(0.2);
  });

  it('keeps an old legacy config exactly as it was', () => {
    const initial: ExecutionConfig = {
      ...DEFAULT_EXECUTION,
      position_sizing: 'volatility_target',
      sizing_value: 0.15,
    };
    render(<Harness initial={initial} />);
    expect(sizing()).toHaveValue('volatility_target');
    expect(config()).toEqual(initial);
    expect(allocationGroup()).not.toBeInTheDocument();
  });
});
