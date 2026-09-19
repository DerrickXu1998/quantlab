import type { Direction, Instrument } from '../api/client';

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

const RULES = ['sma-crossover', 'rsi-threshold', 'breakout-20d'] as const;

interface SignalFiltersProps {
  instruments: Instrument[];
  value: SignalFilterState;
  onChange: (next: SignalFilterState) => void;
}

export function SignalFilters({ instruments, value, onChange }: SignalFiltersProps) {
  const update = (patch: Partial<SignalFilterState>) => onChange({ ...value, ...patch });

  return (
    <form className="signal-filters" onSubmit={(event) => event.preventDefault()}>
      <label>
        Instrument
        <select value={value.instrument} onChange={(e) => update({ instrument: e.target.value })}>
          <option value="">All instruments</option>
          {instruments.map((instrument) => (
            <option key={instrument.symbol} value={instrument.symbol}>
              {instrument.symbol} — {instrument.name}
            </option>
          ))}
        </select>
      </label>

      <label>
        Rule
        <select value={value.signalType} onChange={(e) => update({ signalType: e.target.value })}>
          <option value="">All rules</option>
          {RULES.map((rule) => (
            <option key={rule} value={rule}>
              {rule}
            </option>
          ))}
        </select>
      </label>

      <fieldset className="direction-toggle">
        <legend>Direction</legend>
        <label>
          <input
            type="radio"
            name="direction"
            checked={value.direction === ''}
            onChange={() => update({ direction: '' })}
          />
          All
        </label>
        <label>
          <input
            type="radio"
            name="direction"
            checked={value.direction === 'bullish'}
            onChange={() => update({ direction: 'bullish' })}
          />
          Bullish
        </label>
        <label>
          <input
            type="radio"
            name="direction"
            checked={value.direction === 'bearish'}
            onChange={() => update({ direction: 'bearish' })}
          />
          Bearish
        </label>
      </fieldset>

      <label>
        Start date
        <input
          type="date"
          value={value.startDate}
          onChange={(e) => update({ startDate: e.target.value })}
        />
      </label>

      <label>
        End date
        <input
          type="date"
          value={value.endDate}
          onChange={(e) => update({ endDate: e.target.value })}
        />
      </label>

      <label>
        Sort
        <select
          value={value.sort}
          onChange={(e) => update({ sort: e.target.value as SignalFilterState['sort'] })}
        >
          <option value="date_desc">Newest first</option>
          <option value="date_asc">Oldest first</option>
        </select>
      </label>
    </form>
  );
}
