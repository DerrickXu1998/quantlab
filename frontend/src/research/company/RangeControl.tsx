import { ButtonGroup } from '../../components/ui/layout';
import { cn } from '../../lib/utils';

export type RangeId = '1M' | '3M' | '6M' | '1Y' | '5Y' | '10Y' | 'MAX';

export const RANGES: { id: RangeId; label: string; months: number | null }[] = [
  { id: '1M', label: '1M', months: 1 },
  { id: '3M', label: '3M', months: 3 },
  { id: '6M', label: '6M', months: 6 },
  { id: '1Y', label: '1Y', months: 12 },
  { id: '5Y', label: '5Y', months: 60 },
  { id: '10Y', label: '10Y', months: 120 },
  { id: 'MAX', label: 'Max', months: null },
];

/**
 * Shift an ISO date back by whole months, staying in ISO. The day is clamped
 * to the target month's last day, so 31 March less one month is 28 or 29
 * February rather than rolling over into 3 March.
 */
export function shiftMonths(iso: string, months: number): string {
  const [year, month, day] = iso.split('-').map(Number);
  const target = new Date(Date.UTC(year, month - 1 - months, 1));
  const lastDay = new Date(
    Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0),
  ).getUTCDate();
  target.setUTCDate(Math.min(day, lastDay));
  return target.toISOString().slice(0, 10);
}

/**
 * The first date of the range ending at `asOf`, or null for the whole history.
 *
 * Only the bars' start moves. The warm-up a model needs before that date is
 * the backend's to load, so a 1M window still gets a 50-day average on its
 * first session.
 */
export function rangeStart(asOf: string, range: RangeId): string | null {
  const months = RANGES.find((r) => r.id === range)?.months ?? null;
  return months === null ? null : shiftMonths(asOf, months);
}

export interface RangeControlProps {
  value: RangeId;
  onChange: (value: RangeId) => void;
  /** For the line under the buttons: the window this range resolves to. */
  asOf: string;
}

/**
 * How much history, counted back from the as-of date.
 *
 * The chart and every model applied to it cover the same window, so a model's
 * return and "vs hold" are measured over exactly what is on screen.
 */
export function RangeControl({ value, onChange, asOf }: RangeControlProps) {
  const start = rangeStart(asOf, value);
  return (
    <div className="w-full min-w-0 lg:w-auto lg:shrink-0">
      <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        Range
      </span>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <ButtonGroup label="History range" title="How much history before the as-of date">
          {RANGES.map((range) => (
            <button
              key={range.id}
              type="button"
              aria-pressed={range.id === value}
              onClick={() => onChange(range.id)}
              className={cn(
                'h-11 rounded-sm border px-3 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors lg:h-9 lg:px-2',
                range.id === value
                  ? 'border-primary text-primary'
                  : 'border-border text-muted-foreground hover:text-foreground',
              )}
            >
              {range.label}
            </button>
          ))}
        </ButtonGroup>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {start
          ? `Chart and backtests cover ${start} → ${asOf}.`
          : `Chart and backtests cover the full history up to ${asOf}.`}
      </p>
    </div>
  );
}
