import type { Direction, Instrument } from '../api/client';
import { Input, Label, Select } from './ui/field';

export interface SignalFilterState {
  instrument: string;
  signalType: string;
  direction: '' | Direction;
  startDate: string;
  endDate: string;
  sort: 'date_asc' | 'date_desc';
}

export const EMPTY_FILTERS: SignalFilterState = {
  instrument: '',
  signalType: '',
  direction: '',
  startDate: '',
  endDate: '',
  sort: 'date_desc',
};

interface SignalFiltersProps {
  instruments: Instrument[];
  /** Model names from the catalog. Passed in rather than hardcoded so
   *  registering a model is enough for it to appear (Constitution II). */
  ruleNames: string[];
  value: SignalFilterState;
  onChange: (next: SignalFilterState) => void;
}

const radioClasses =
  'h-3.5 w-3.5 accent-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring';

export function SignalFilters({ instruments, ruleNames, value, onChange }: SignalFiltersProps) {
  const update = (patch: Partial<SignalFilterState>) => onChange({ ...value, ...patch });

  return (
    <form
      // A grid, not a wrapping row: a <select> sizes itself to its widest
      // option, so the instrument picker was 400px wide and pushed the form to
      // three ragged rows that changed count with the viewport. Equal auto-fit
      // columns wrap predictably and leave no void under the form.
      className="signal-filters grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] items-end gap-3 rounded-sm border border-border bg-card p-3"
      onSubmit={(event) => event.preventDefault()}
    >
      <Label>
        Instrument
        <Select value={value.instrument} onChange={(e) => update({ instrument: e.target.value })}>
          <option value="">All instruments</option>
          {instruments.map((instrument) => (
            <option key={instrument.symbol} value={instrument.symbol}>
              {instrument.symbol} — {instrument.name}
            </option>
          ))}
        </Select>
      </Label>

      <Label>
        Rule
        <Select value={value.signalType} onChange={(e) => update({ signalType: e.target.value })}>
          <option value="">All rules</option>
          {ruleNames.map((rule) => (
            <option key={rule} value={rule}>
              {rule}
            </option>
          ))}
        </Select>
      </Label>

      <fieldset className="direction-toggle rounded-sm border border-border px-3 py-2">
        <legend className="px-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          Direction
        </legend>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-foreground">
          <label className="inline-flex items-center gap-1.5">
            <input
              type="radio"
              name="direction"
              className={radioClasses}
              checked={value.direction === ''}
              onChange={() => update({ direction: '' })}
            />
            All
          </label>
          <label className="inline-flex items-center gap-1.5">
            <input
              type="radio"
              name="direction"
              className={radioClasses}
              checked={value.direction === 'bullish'}
              onChange={() => update({ direction: 'bullish' })}
            />
            Bullish
          </label>
          <label className="inline-flex items-center gap-1.5">
            <input
              type="radio"
              name="direction"
              className={radioClasses}
              checked={value.direction === 'bearish'}
              onChange={() => update({ direction: 'bearish' })}
            />
            Bearish
          </label>
        </div>
      </fieldset>

      <Label>
        Start date
        <Input
          type="date"
          value={value.startDate}
          onChange={(e) => update({ startDate: e.target.value })}
        />
      </Label>

      <Label>
        End date
        <Input
          type="date"
          value={value.endDate}
          onChange={(e) => update({ endDate: e.target.value })}
        />
      </Label>

      <Label>
        Sort
        <Select
          value={value.sort}
          onChange={(e) => update({ sort: e.target.value as SignalFilterState['sort'] })}
        >
          <option value="date_desc">Newest first</option>
          <option value="date_asc">Oldest first</option>
        </Select>
      </Label>
    </form>
  );
}
