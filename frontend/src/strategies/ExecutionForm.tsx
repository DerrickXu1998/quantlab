import { useId, type ReactNode } from 'react';
import type { ExecutionConfig, FillTiming, PositionSizing } from '../api/types';
import { FILL_TIMINGS, POSITION_SIZING_MODES, SIZING_VALUE_MEANING } from '../api/types';
import { Input, Select } from '../components/ui/field';

/**
 * Execution criteria: §4 of the contract, field for field.
 *
 * Every one of these used to be a hardcoded assumption ("the close of the
 * signal date, whole sleeve, no costs, no stops"), which meant a backtest
 * reported a result produced by rules the user never saw. They are controls
 * now, and each one carries a line saying what it does to the result — a
 * number whose effect you cannot state is a number you cannot reason about.
 *
 * Percentages are entered as percentages and stored as the fractions the API
 * expects. That is unit handling, not analysis: nothing here evaluates a
 * price, a return or an indicator (Constitution V).
 */

const MICRO = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

const SIZING_LABELS: Record<PositionSizing, string> = {
  equal_weight: 'Equal weight',
  fixed_fraction: 'Fixed fraction of equity',
  fixed_notional: 'Fixed cash per trade',
  volatility_target: 'Volatility target',
};

const SIZING_EXPLAINERS: Record<PositionSizing, string> = {
  equal_weight: 'Splits the book evenly across whatever is open at the time.',
  fixed_fraction: 'Commits the same share of current equity to every position.',
  fixed_notional: 'Commits the same cash amount every time, however the book has grown.',
  volatility_target: 'Sizes each position so its own volatility hits a target.',
};

const FILL_TIMING_LABELS: Record<FillTiming, string> = {
  signal_close: 'Close of the signal bar',
  next_open: 'Next bar’s open',
};

const FILL_TIMING_EXPLAINERS: Record<FillTiming, string> = {
  signal_close:
    'Fills at the close of the bar that produced the signal. Optimistic: in reality you cannot know the close until it has happened.',
  next_open:
    'Fills at the next bar’s open, which is the first price you could genuinely have traded. A signal on the final bar has no bar to fill on and is dropped.',
};

/** Fractions on the wire, percentages on the screen. Rounded to kill 0.1+0.2. */
function toFraction(percentValue: number): number {
  return Number((percentValue / 100).toFixed(8));
}

function toPercentString(fraction: number | null): string {
  if (fraction === null) return '';
  return String(Number((fraction * 100).toFixed(6)));
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 border-t border-border pt-3">
      <legend className={MICRO}>{title}</legend>
      {note ? <p className="text-[11px] text-muted-foreground">{note}</p> : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

function Field({
  label,
  explainer,
  suffix,
  children,
  full,
}: {
  label: string;
  explainer: string;
  suffix?: string;
  children: (ids: { id: string; describedBy: string }) => ReactNode;
  full?: boolean;
}) {
  const id = useId();
  const describedBy = `${id}-help`;
  return (
    <div className={`space-y-1 ${full ? 'sm:col-span-2' : ''}`}>
      <label className={MICRO} htmlFor={id}>
        {label}
      </label>
      <div className="flex items-center gap-2">
        {children({ id, describedBy })}
        {suffix ? <span className={`${MICRO} shrink-0`}>{suffix}</span> : null}
      </div>
      <p id={describedBy} className="text-[11px] text-muted-foreground">
        {explainer}
      </p>
    </div>
  );
}

export interface ExecutionFormProps {
  value: ExecutionConfig;
  onChange: (next: ExecutionConfig) => void;
}

export function ExecutionForm({ value, onChange }: ExecutionFormProps) {
  const patch = (next: Partial<ExecutionConfig>) => onChange({ ...value, ...next });

  /** Blank means "off", not zero: a 0% stop would exit instantly. */
  const optionalNumber = (raw: string): number | null => {
    if (raw.trim() === '') return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const sizingMeaning = SIZING_VALUE_MEANING[value.position_sizing];

  return (
    <div className="space-y-4" data-testid="execution-form">
      <Section
        title="Capital & sizing"
        note="How much money the book starts with, and how much of it any one position may take."
      >
        <Field
          label="Initial capital"
          explainer="The notional book the run starts with. Every figure the run reports is measured against it."
          suffix="USD"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="1000"
              aria-describedby={describedBy}
              value={String(value.initial_capital)}
              onChange={(event) => patch({ initial_capital: Number(event.target.value) })}
            />
          )}
        </Field>

        <Field
          label="Position sizing"
          explainer={SIZING_EXPLAINERS[value.position_sizing]}
        >
          {({ id, describedBy }) => (
            <Select
              id={id}
              aria-describedby={describedBy}
              value={value.position_sizing}
              onChange={(event) => {
                const mode = event.target.value as PositionSizing;
                // Dropping the value when the mode stops reading it keeps a
                // stale number from being recorded as if it had an effect.
                patch({
                  position_sizing: mode,
                  sizing_value:
                    SIZING_VALUE_MEANING[mode] === undefined
                      ? null
                      : (value.sizing_value ?? (mode === 'fixed_notional' ? 10000 : 0.2)),
                });
              }}
            >
              {POSITION_SIZING_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {SIZING_LABELS[mode]}
                </option>
              ))}
            </Select>
          )}
        </Field>

        {/* Only the three modes that read it. Equal weight has no value to set,
            and a field that is ignored is worse than no field. */}
        {sizingMeaning ? (
          <Field
            label={
              value.position_sizing === 'fixed_notional' ? 'Cash per trade' : 'Sizing value'
            }
            explainer={sizingMeaning}
            suffix={value.position_sizing === 'fixed_notional' ? 'USD' : 'fraction'}
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="number"
                step="any"
                min={0}
                data-testid="execution-sizing-value"
                aria-describedby={describedBy}
                value={value.sizing_value === null ? '' : String(value.sizing_value)}
                onChange={(event) => patch({ sizing_value: optionalNumber(event.target.value) })}
              />
            )}
          </Field>
        ) : null}

        <Field
          label="Max positions"
          explainer="Cap on how many positions may be open at once. Blank means no cap, and a wide signal can then take the whole book."
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={1}
              step="1"
              placeholder="no cap"
              aria-describedby={describedBy}
              value={value.max_positions === null ? '' : String(value.max_positions)}
              onChange={(event) => patch({ max_positions: optionalNumber(event.target.value) })}
            />
          )}
        </Field>

        <Field
          label="Max position size"
          explainer="Ceiling for any single name, as a share of equity. 100% allows one position to be the entire book."
          suffix="%"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              max={100}
              step="any"
              aria-describedby={describedBy}
              value={toPercentString(value.max_position_pct)}
              onChange={(event) =>
                patch({ max_position_pct: toFraction(Number(event.target.value)) })
              }
            />
          )}
        </Field>
      </Section>

      <Section
        title="Entry & exit timing"
        note="When an order that a signal asked for actually gets filled, and how long a position is allowed to live."
      >
        <Field label="Fill timing" explainer={FILL_TIMING_EXPLAINERS[value.fill_timing]} full>
          {({ id, describedBy }) => (
            <Select
              id={id}
              aria-describedby={describedBy}
              value={value.fill_timing}
              onChange={(event) => patch({ fill_timing: event.target.value as FillTiming })}
            >
              {FILL_TIMINGS.map((timing) => (
                <option key={timing} value={timing}>
                  {FILL_TIMING_LABELS[timing]}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field
          label="Min holding days"
          explainer="Signal exits are suppressed until a position is this old. Protective exits ignore it — a stop still fires on day one."
          suffix="bars"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="1"
              aria-describedby={describedBy}
              value={String(value.min_holding_days)}
              onChange={(event) => patch({ min_holding_days: Number(event.target.value) })}
            />
          )}
        </Field>

        <Field
          label="Max holding days"
          explainer="Forces an exit after this many bars, whatever the signals say. Blank lets a position run to the end of the window."
          suffix="bars"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={1}
              step="1"
              placeholder="no limit"
              aria-describedby={describedBy}
              value={value.max_holding_days === null ? '' : String(value.max_holding_days)}
              onChange={(event) => patch({ max_holding_days: optionalNumber(event.target.value) })}
            />
          )}
        </Field>

        <Field
          label="Cooldown"
          explainer="Bars to wait after closing a name before that name may be entered again. Stops one choppy instrument monopolising the book."
          suffix="bars"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="1"
              aria-describedby={describedBy}
              value={String(value.cooldown_days)}
              onChange={(event) => patch({ cooldown_days: Number(event.target.value) })}
            />
          )}
        </Field>

        <Field
          label="Allow shorts"
          explainer="When on, a bearish entry opens a short and a bullish signal covers it. When off, bearish entries are simply ignored."
        >
          {({ id, describedBy }) => (
            <span className="flex h-9 items-center">
              <input
                id={id}
                type="checkbox"
                aria-describedby={describedBy}
                checked={value.allow_shorts}
                onChange={(event) => patch({ allow_shorts: event.target.checked })}
                className="h-4 w-4 rounded-sm border-input accent-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </span>
          )}
        </Field>
      </Section>

      <Section
        title="Risk controls"
        note="Price-triggered exits. They are tested against the bar's own high and low, so they can fire on a bar the signals never saw."
      >
        <Field
          label="Stop loss"
          explainer="Exit once price has moved this far against the entry. Blank means no stop at all."
          suffix="%"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="any"
              placeholder="off"
              aria-describedby={describedBy}
              value={toPercentString(value.stop_loss_pct)}
              onChange={(event) => {
                const raw = optionalNumber(event.target.value);
                patch({ stop_loss_pct: raw === null ? null : toFraction(raw) });
              }}
            />
          )}
        </Field>

        <Field
          label="Take profit"
          explainer="Exit once price has moved this far in favour of the entry. Caps the winners as well as banking them."
          suffix="%"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="any"
              placeholder="off"
              aria-describedby={describedBy}
              value={toPercentString(value.take_profit_pct)}
              onChange={(event) => {
                const raw = optionalNumber(event.target.value);
                patch({ take_profit_pct: raw === null ? null : toFraction(raw) });
              }}
            />
          )}
        </Field>

        <Field
          label="Trailing stop"
          explainer="Exit once price falls this far from the best close seen while the position was held."
          suffix="%"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="any"
              placeholder="off"
              aria-describedby={describedBy}
              value={toPercentString(value.trailing_stop_pct)}
              onChange={(event) => {
                const raw = optionalNumber(event.target.value);
                patch({ trailing_stop_pct: raw === null ? null : toFraction(raw) });
              }}
            />
          )}
        </Field>

        <Field
          label="ATR stop multiple"
          explainer="Places the stop this many ATRs from the entry, so a volatile name gets more room than a quiet one."
          suffix="× ATR"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="any"
              placeholder="off"
              aria-describedby={describedBy}
              value={value.atr_stop_multiple === null ? '' : String(value.atr_stop_multiple)}
              onChange={(event) => patch({ atr_stop_multiple: optionalNumber(event.target.value) })}
            />
          )}
        </Field>

        {/* The period only means anything once a multiple is set. */}
        {value.atr_stop_multiple !== null ? (
          <Field
            label="ATR period"
            explainer="Bars of history the ATR behind that stop is measured over."
            suffix="bars"
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="number"
                min={1}
                step="1"
                data-testid="execution-atr-period"
                aria-describedby={describedBy}
                value={String(value.atr_period)}
                onChange={(event) => patch({ atr_period: Number(event.target.value) })}
              />
            )}
          </Field>
        ) : null}

        <ResolutionOrder />
      </Section>

      <Section
        title="Costs"
        note="Charged on both sides of every trade. A backtest with costs switched off is the single easiest way to make a losing strategy look profitable."
      >
        <Field
          label="Commission"
          explainer="Basis points of notional, deducted as cash on entry and again on exit."
          suffix="bps"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="any"
              aria-describedby={describedBy}
              value={String(value.commission_bps)}
              onChange={(event) => patch({ commission_bps: Number(event.target.value) })}
            />
          )}
        </Field>

        <Field
          label="Slippage"
          explainer="Basis points the fill moves against you — buys fill higher, sells fill lower — on each side."
          suffix="bps"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="any"
              aria-describedby={describedBy}
              value={String(value.slippage_bps)}
              onChange={(event) => patch({ slippage_bps: Number(event.target.value) })}
            />
          )}
        </Field>
      </Section>
    </div>
  );
}

/**
 * The resolution order, stated where the criteria are set.
 *
 * This is not a footnote. Two criteria can both be satisfiable on the same
 * bar, and which one is taken changes the reported result — so a user who does
 * not know that a stop beats a target inside one bar cannot interpret their
 * own numbers.
 */
export function ResolutionOrder() {
  return (
    <details
      data-testid="resolution-order"
      className="sm:col-span-2 border border-border bg-background/50 px-3 py-2"
    >
      <summary className={`${MICRO} cursor-pointer`}>
        What happens when two of these fire on the same bar
      </summary>
      <ol className="mt-2 list-decimal space-y-1 pl-4 text-[11px] text-muted-foreground">
        <li>Mark the bar.</li>
        <li>
          Protective exits, in this order: stop loss → trailing stop → take profit → max holding
          days.
        </li>
        <li>Signal exits, once min holding days has elapsed.</li>
        <li>Signal entries, subject to max positions, cooldown, cash and every filter.</li>
      </ol>
      <p className="mt-2 text-[11px] text-muted-foreground">
        A stop and a target both inside one bar’s high–low resolve to the <strong>stop</strong>.
        Intraday order is unknowable from a daily bar, and assuming the favourable one is how
        backtests flatter themselves. Stops fill at the stop price; a gap through the level fills at
        the open, which is worse than the level and is the honest outcome.
      </p>
    </details>
  );
}
