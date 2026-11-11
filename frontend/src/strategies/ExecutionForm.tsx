import { useId, type ReactNode } from 'react';
import type {
  ExecutionConfig,
  FillTiming,
  IntradayResolution,
  PositionSizing,
  PriceAdjustment,
  RebalanceFrequency,
} from '../api/types';
import {
  ALLOCATION_DEFAULTS,
  ALLOCATION_FIELDS,
  ALLOCATION_SIZING_MODES,
  FILL_TIMINGS,
  FILL_TIMING_EXPLAINERS,
  FILL_TIMING_LABELS,
  INTRADAY_RESOLUTIONS,
  INTRADAY_RESOLUTION_EXPLAINERS,
  INTRADAY_RESOLUTION_LABELS,
  MINUTE_ONLY_FILL_TIMINGS,
  POSITION_SIZING_MODES,
  PRICE_ADJUSTMENTS,
  PRICE_ADJUSTMENT_EXPLAINERS,
  PRICE_ADJUSTMENT_LABELS,
  REBALANCE_FREQUENCIES,
  REBALANCE_FREQUENCY_LABELS,
  SIZING_VALUE_MEANING,
  isAllocationSizing,
} from '../api/types';
import { Input, Select } from '../components/ui/field';
import { Term } from '../glossary/Term';
import type { TermId } from '../glossary/terms';

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

const MICRO = 'type-label text-muted-foreground';

const SIZING_LABELS: Record<PositionSizing, string> = {
  equal_weight: 'Equal weight',
  fixed_fraction: 'Fixed fraction of equity',
  fixed_notional: 'Fixed cash per trade',
  volatility_target: 'Volatility target',
  equal_active: 'Equal active weight',
  signal_strength: 'Signal strength',
  signal_inverse_volatility: 'Signal strength ÷ volatility',
};

const INDEPENDENT_SIZING_MODES = POSITION_SIZING_MODES.filter((mode) => !isAllocationSizing(mode));

const SIZING_EXPLAINERS: Record<PositionSizing, string> = {
  equal_weight: 'Splits the book evenly across whatever is open at the time.',
  fixed_fraction: 'Commits the same share of current equity to every position.',
  fixed_notional: 'Commits the same cash amount every time, however the book has grown.',
  volatility_target: 'Sizes each position so its own volatility hits a target.',
  equal_active:
    'Portfolio allocation: every active signal gets the same target weight of one shared book, and open positions are resized as signals come and go.',
  signal_strength:
    'Portfolio allocation: target weights in proportion to each signal’s strength — the weighted share of entry components that agree — rebalanced across the shared book.',
  signal_inverse_volatility:
    'Portfolio allocation: target weights in proportion to signal strength divided by trailing volatility, so a quiet name gets more than a jumpy one with the same conviction.',
};

const REBALANCE_EXPLAINERS: Record<RebalanceFrequency, string> = {
  on_signal:
    'Targets are recomputed on any session where a signal opens, strengthens, weakens or closes an allocation.',
  daily: 'Targets are recomputed every session, so price drift is traded back to target daily.',
  weekly: 'Targets are recomputed on the first session of each week, and on nothing in between.',
  monthly: 'Targets are recomputed on the first session of each month, and on nothing in between.',
};

/**
 * The config after switching sizing mode, with every value the new mode would
 * not read dropped: a stale number left behind would be recorded on the run as
 * if it had an effect, and a legacy mode refuses the allocation fields
 * outright. Between allocation modes the shared settings carry over, because
 * all three read them.
 */
export function withSizingMode(value: ExecutionConfig, mode: PositionSizing): ExecutionConfig {
  const next: ExecutionConfig = { ...value, position_sizing: mode };
  if (SIZING_VALUE_MEANING[mode] === undefined) {
    next.sizing_value = null;
  } else if (mode !== value.position_sizing) {
    // Each mode reads the value differently (cash, a fraction of equity, a
    // target volatility), so another mode's number is never carried over.
    next.sizing_value = mode === 'fixed_notional' ? 10000 : 0.2;
  }
  if (!isAllocationSizing(mode)) {
    for (const field of ALLOCATION_FIELDS) delete next[field];
  }
  return next;
}

const COST_PROFILES = {
  idealized: { commission_bps: 0, slippage_bps: 0 },
  base: { commission_bps: 1, slippage_bps: 5 },
  stressed: { commission_bps: 2, slippage_bps: 20 },
} as const;

type CostProfile = keyof typeof COST_PROFILES | 'custom';

const COST_PROFILE_LABELS: Record<CostProfile, string> = {
  idealized: 'Idealized — no costs',
  base: 'Base — 1 bps commission + 5 bps slippage',
  stressed: 'Stressed — 2 bps commission + 20 bps slippage',
  custom: 'Custom',
};

function costProfileOf(value: ExecutionConfig): CostProfile {
  for (const [profile, costs] of Object.entries(COST_PROFILES)) {
    if (value.commission_bps === costs.commission_bps && value.slippage_bps === costs.slippage_bps) {
      return profile as CostProfile;
    }
  }
  return 'custom';
}

/** Fractions on the wire, percentages on the screen. Rounded to kill 0.1+0.2. */
function toFraction(percentValue: number): number {
  return Number((percentValue / 100).toFixed(8));
}

function toPercentString(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined) return '';
  return String(Number((fraction * 100).toFixed(6)));
}

/** Blank means "off", not zero: a 0% stop would exit instantly. */
function optionalNumber(raw: string): number | null {
  if (raw.trim() === '') return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

/** A percent typed on screen as its fraction; blank is the backend's default. */
function optionalFraction(raw: string): number | null {
  const parsed = optionalNumber(raw);
  return parsed === null ? null : toFraction(parsed);
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 border-t border-border pt-3">
      <legend className={MICRO}>{title}</legend>
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

function Field({
  label,
  term,
  explainer,
  suffix,
  children,
  full,
}: {
  label: string;
  /** The glossary entry the label explains, on hover. */
  term?: TermId;
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
        {term ? <Term id={term}>{label}</Term> : label}
      </label>
      <div className="flex items-center gap-2">
        {children({ id, describedBy })}
        {suffix ? <span className={`${MICRO} shrink-0`}>{suffix}</span> : null}
      </div>
      <p id={describedBy} className="text-xs text-muted-foreground">
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
  // Set from the Universe & window panel; here it only rules options out.
  const intradayBars = (value.bar_frequency ?? '1d') !== '1d';

  const sizingMeaning = SIZING_VALUE_MEANING[value.position_sizing];
  const allocation = isAllocationSizing(value.position_sizing);

  return (
    <div className="space-y-4" data-testid="execution-form">
      <Section
        title="Capital & sizing"
        note="How much money the book starts with, and how much of it any one position may take."
      >
        <Field
          label="Initial capital"
          term="initial_capital"
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
          term="position_sizing"
          explainer={SIZING_EXPLAINERS[value.position_sizing]}
        >
          {({ id, describedBy }) => (
            <Select
              id={id}
              aria-describedby={describedBy}
              value={value.position_sizing}
              onChange={(event) =>
                onChange(withSizingMode(value, event.target.value as PositionSizing))
              }
            >
              <optgroup label="Independent sizing">
                {INDEPENDENT_SIZING_MODES.map((mode) => (
                  <option key={mode} value={mode}>
                    {SIZING_LABELS[mode]}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Portfolio allocation (shared capital)">
                {ALLOCATION_SIZING_MODES.map((mode) => (
                  <option key={mode} value={mode}>
                    {SIZING_LABELS[mode]}
                  </option>
                ))}
              </optgroup>
            </Select>
          )}
        </Field>

        {/* Only the three modes that read it. Equal weight has no value to set,
            and a field that is ignored is worse than no field. */}
        {sizingMeaning ? (
          <Field
            label={value.position_sizing === 'fixed_notional' ? 'Cash per trade' : 'Sizing value'}
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
          term="max_positions"
          explainer={
            allocation
              ? 'Cap on how many names hold a target at once: the strongest signals are chosen, ties by symbol. Blank means every active signal shares the book.'
              : 'Cap on how many positions may be open at once. Blank means no cap, and a wide signal can then take the whole book.'
          }
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
          term="max_position_pct"
          explainer={
            allocation
              ? 'Ceiling on any one target weight, as a share of equity. Weight cut by the cap goes to the uncapped names; what none can take stays in cash.'
              : 'Ceiling for any single name, as a share of equity. 100% allows one position to be the entire book.'
          }
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

      {allocation ? <AllocationSection value={value} patch={patch} /> : null}

      <Section
        title="Entry & exit timing"
        note="When an order that a signal asked for actually gets filled, and how long a position is allowed to live."
      >
        {/* Only daily bars have a choice to make: intraday bars already step
            through the session, so the control would be a disabled select
            explaining itself. */}
        {intradayBars ? null : (
          <Field
            label="Execution accuracy"
            term="execution_accuracy"
            explainer={INTRADAY_RESOLUTION_EXPLAINERS[value.intraday_resolution]}
            full
          >
            {({ id, describedBy }) => (
              <Select
                id={id}
                aria-describedby={describedBy}
                value={value.intraday_resolution}
                onChange={(event) => {
                  const intraday_resolution = event.target.value as IntradayResolution;
                  // A VWAP fill needs minute bars: back to its daily stand-in
                  // rather than leaving a combination the engine refuses.
                  const fill_timing =
                    intraday_resolution === 'daily' &&
                    MINUTE_ONLY_FILL_TIMINGS.includes(value.fill_timing)
                      ? 'next_typical'
                      : value.fill_timing;
                  patch({ intraday_resolution, fill_timing });
                }}
              >
                {INTRADAY_RESOLUTIONS.map((mode) => (
                  <option key={mode} value={mode}>
                    {INTRADAY_RESOLUTION_LABELS[mode]}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}

        <Field
          label="Fill timing"
          term="fill_timing"
          explainer={FILL_TIMING_EXPLAINERS[value.fill_timing]}
          full
        >
          {({ id, describedBy }) => (
            <Select
              id={id}
              aria-describedby={describedBy}
              value={value.fill_timing}
              onChange={(event) => patch({ fill_timing: event.target.value as FillTiming })}
            >
              {FILL_TIMINGS.map((timing) => {
                const needsMinute =
                  MINUTE_ONLY_FILL_TIMINGS.includes(timing) &&
                  (value.intraday_resolution !== 'minute' || intradayBars);
                return (
                  <option key={timing} value={timing} disabled={needsMinute}>
                    {FILL_TIMING_LABELS[timing]}
                    {needsMinute ? ' — needs Minute accuracy' : ''}
                  </option>
                );
              })}
            </Select>
          )}
        </Field>

        <Field
          label="Min holding days"
          term="min_holding_days"
          explainer="Signal exits are suppressed until a position has been held this many trading days. Protective exits ignore it — a stop still fires on day one. Days at every bar size: on 5-minute bars, 1 means the next session."
          suffix="days"
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
          term="max_holding_days"
          explainer="Forces an exit once a position has been held this many trading days, whatever the signals say: at the first bar of that session. Days at every bar size, never bars. Blank lets a position run to the end of the window."
          suffix="days"
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
          term="cooldown"
          explainer="Trading days to wait after closing a name before it may be entered again; 1 means not before the next session. Stops one choppy instrument monopolising the book."
          suffix="days"
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
          term="allow_shorts"
          explainer="When on, a bearish entry opens a short and a bullish signal covers it. When off, bearish entries are simply ignored."
        >
          {({ id, describedBy }) => (
            <label htmlFor={id} className="flex h-11 w-11 items-center lg:h-9 lg:w-auto">
              <input
                id={id}
                type="checkbox"
                aria-describedby={describedBy}
                checked={value.allow_shorts}
                onChange={(event) => patch({ allow_shorts: event.target.checked })}
                className="h-4 w-4 rounded-sm border-input accent-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </label>
          )}
        </Field>
      </Section>

      <Section
        title="Risk controls"
        note="Price-triggered exits. They are tested against the bar's own high and low, so they can fire on a bar the signals never saw."
      >
        <Field
          label="Stop loss"
          term="stop_loss"
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
          term="take_profit"
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
          term="trailing_stop"
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
          term="atr_stop"
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
            term="atr"
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
          label="Cost profile"
          explainer="Presets set commission and slippage per side. Editing either amount makes the profile custom; the numeric values are what the run records and executes."
          full
        >
          {({ id, describedBy }) => (
            <Select
              id={id}
              aria-describedby={describedBy}
              value={costProfileOf(value)}
              onChange={(event) => {
                const profile = event.target.value as CostProfile;
                if (profile !== 'custom') patch(COST_PROFILES[profile]);
              }}
            >
              {(Object.keys(COST_PROFILE_LABELS) as CostProfile[]).map((profile) => (
                <option key={profile} value={profile} disabled={profile === 'custom'}>
                  {COST_PROFILE_LABELS[profile]}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field
          label="Commission"
          term="commission"
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
          term="slippage"
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

        {/* Only with shorts on: a long-only book borrows nothing, and a field
            that does nothing is a field someone fills in and trusts. */}
        {value.allow_shorts ? (
          <Field
            label="Short borrow"
            term="borrow_cost"
            explainer="Annual cost of borrowing the stock you short, as basis points of the short's market value, charged each day it is held. Liquid large caps: 25-50 bps; hard to borrow: hundreds. 0 means shorting is free — which it is not."
            suffix="bps / yr"
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="number"
                min={0}
                max={5000}
                step="any"
                aria-describedby={describedBy}
                value={String(value.borrow_cost_bps ?? 0)}
                onChange={(event) => patch({ borrow_cost_bps: Number(event.target.value) })}
              />
            )}
          </Field>
        ) : null}
      </Section>

      <Section
        title="Liquidity & order lifetime"
        note="A transparent capacity constraint using each bar's traded volume. It is not an order-book or market-impact model."
      >
        <Field
          label="Max volume participation"
          explainer="Maximum share of a bar's volume one order may fill. Remainders carry forward; blank means unlimited liquidity. Intraday bars use conservative IEX-only volume."
          suffix="%"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={0}
              max={100}
              step="any"
              placeholder="unlimited"
              aria-describedby={describedBy}
              value={toPercentString(value.max_volume_participation)}
              onChange={(event) => {
                const raw = optionalNumber(event.target.value);
                patch({ max_volume_participation: raw === null ? null : toFraction(raw) });
              }}
            />
          )}
        </Field>

        <Field
          label="Order expiry"
          explainer="Trading sessions a partially filled signal order remains active. Protective-exit remainders stay active until filled or the window ends."
          suffix="days"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={1}
              step={1}
              aria-describedby={describedBy}
              value={String(value.order_expiry_days)}
              onChange={(event) => patch({ order_expiry_days: Number(event.target.value) })}
            />
          )}
        </Field>
      </Section>

      <Section
        title="Splits & dividends"
        note="Stored prices are what traded. This decides whether signals see a split as a crash, and whether a held position collects its dividends."
      >
        <Field
          label="Price adjustment"
          term="price_adjustment"
          explainer={PRICE_ADJUSTMENT_EXPLAINERS[value.price_adjustment ?? 'split_dividend']}
          full
        >
          {({ id, describedBy }) => (
            <Select
              id={id}
              aria-describedby={describedBy}
              value={value.price_adjustment ?? 'split_dividend'}
              onChange={(event) =>
                patch({ price_adjustment: event.target.value as PriceAdjustment })
              }
            >
              {PRICE_ADJUSTMENTS.map((mode) => (
                <option key={mode} value={mode}>
                  {PRICE_ADJUSTMENT_LABELS[mode]}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </Section>
    </div>
  );
}

/**
 * The settings only the shared-capital modes read, shown only under them.
 *
 * The explainer leads because the behaviour is the surprising part: under
 * these modes a signal on one name can shrink a position in another, which
 * independent sizing never does.
 */
function AllocationSection({
  value,
  patch,
}: {
  value: ExecutionConfig;
  patch: (next: Partial<ExecutionConfig>) => void;
}) {
  const frequency = value.rebalance_frequency ?? ALLOCATION_DEFAULTS.rebalance_frequency;
  return (
    <Section title="Portfolio allocation">
      <p data-testid="allocation-explainer" className="text-xs text-muted-foreground sm:col-span-2">
        These modes share one pool of capital. Every active signal holds a target weight and the
        book is rebalanced toward those targets, so a new or stronger signal on one name can trim
        positions in others, and a weaker one is partially reduced rather than closed. Independent
        sizing such as equal weight gives each position its own sleeve, sized once at entry and
        never resized by other signals.
      </p>

      <Field
        label="Target exposure"
        term="target_exposure"
        explainer="Gross exposure the target weights add up to, as a share of equity (longs plus shorts). The rest stays in cash. Blank means 100%."
        suffix="%"
      >
        {({ id, describedBy }) => (
          <Input
            id={id}
            type="number"
            min={0}
            max={100}
            step="any"
            placeholder="100"
            data-testid="execution-target-exposure"
            aria-describedby={describedBy}
            value={toPercentString(value.target_exposure)}
            onChange={(event) => patch({ target_exposure: optionalFraction(event.target.value) })}
          />
        )}
      </Field>

      <Field
        label="Min allocation score"
        term="allocation_score"
        explainer="Signals whose strength (the weighted share of entry components that agree) is below this get no allocation. Blank means every eligible signal counts."
        suffix="%"
      >
        {({ id, describedBy }) => (
          <Input
            id={id}
            type="number"
            min={0}
            max={100}
            step="any"
            placeholder="0"
            data-testid="execution-min-allocation-score"
            aria-describedby={describedBy}
            value={toPercentString(value.min_allocation_score)}
            onChange={(event) =>
              patch({ min_allocation_score: optionalFraction(event.target.value) })
            }
          />
        )}
      </Field>

      {value.position_sizing === 'signal_inverse_volatility' ? (
        <Field
          label="Volatility lookback"
          term="realised_volatility"
          explainer="Bars of history each name's realised volatility is measured over. It is the same setting as the ATR period, so an ATR stop measures over it too. A name without enough history gets no allocation."
          suffix="bars"
        >
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="number"
              min={2}
              step="1"
              data-testid="execution-volatility-lookback"
              aria-describedby={describedBy}
              value={String(value.atr_period)}
              onChange={(event) => patch({ atr_period: Number(event.target.value) })}
            />
          )}
        </Field>
      ) : null}

      <Field label="Rebalance" term="rebalance" explainer={REBALANCE_EXPLAINERS[frequency]} full>
        {({ id, describedBy }) => (
          <Select
            id={id}
            aria-describedby={describedBy}
            data-testid="execution-rebalance-frequency"
            value={frequency}
            onChange={(event) =>
              patch({ rebalance_frequency: event.target.value as RebalanceFrequency })
            }
          >
            {REBALANCE_FREQUENCIES.map((option) => (
              <option key={option} value={option}>
                {REBALANCE_FREQUENCY_LABELS[option]}
              </option>
            ))}
          </Select>
        )}
      </Field>

      <Field
        label="Rebalance threshold"
        term="rebalance_threshold"
        explainer="A position is traded only when its weight is at least this far from target, so small drifts do not pay costs. Exits are never held back by it. Blank means 0%."
        suffix="%"
      >
        {({ id, describedBy }) => (
          <Input
            id={id}
            type="number"
            min={0}
            max={100}
            step="any"
            placeholder="0"
            data-testid="execution-rebalance-threshold"
            aria-describedby={describedBy}
            value={toPercentString(value.rebalance_threshold)}
            onChange={(event) =>
              patch({ rebalance_threshold: optionalFraction(event.target.value) })
            }
          />
        )}
      </Field>

      <Field
        label="Max turnover"
        term="max_turnover"
        explainer="Most one rebalance may trade, as the sum of weight changes: 200% sells the whole book and buys a new one. A larger rebalance is scaled down in proportion; exits are never held back. Blank means no cap."
        suffix="%"
      >
        {({ id, describedBy }) => (
          <Input
            id={id}
            type="number"
            min={0}
            max={200}
            step="any"
            placeholder="no cap"
            data-testid="execution-max-turnover"
            aria-describedby={describedBy}
            value={toPercentString(value.max_turnover)}
            onChange={(event) => patch({ max_turnover: optionalFraction(event.target.value) })}
          />
        )}
      </Field>
    </Section>
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
      <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-muted-foreground">
        <li>Mark the bar.</li>
        <li>
          Protective exits, in this order: stop loss → trailing stop → take profit → max holding
          days.
        </li>
        <li>Signal exits, once min holding days has elapsed.</li>
        <li>Signal entries, subject to max positions, cooldown, cash and every filter.</li>
      </ol>
      <p className="mt-2 text-xs text-muted-foreground">
        A stop and a target both inside one bar’s high–low resolve to the <strong>stop</strong>.
        Intraday order is unknowable from a daily bar, and assuming the favourable one is how
        backtests flatter themselves. Stops fill at the stop price; a gap through the level fills at
        the open, which is worse than the level and is the honest outcome.
      </p>
    </details>
  );
}
