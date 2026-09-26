import { CalendarDays } from 'lucide-react';
import { useId } from 'react';
import { ButtonGroup } from '../../components/ui/layout';
import { fieldClasses } from '../../components/ui/field';
import { cn } from '../../lib/utils';

/** Shift an ISO date by whole years, staying in ISO. */
export function shiftYears(iso: string, years: number): string {
  const [year, month, day] = iso.split('-').map(Number);
  const shifted = new Date(Date.UTC(year - years, month - 1, day));
  return shifted.toISOString().slice(0, 10);
}

export interface AsOfPreset {
  label: string;
  value: string;
}

/**
 * The dates worth one click.
 *
 * Deliberately few and deliberately round. The interesting question this screen
 * answers is "what did the accounts say *then*", and the cheapest way to make
 * that question askable is a button that moves the cut back a year at a time.
 */
export function presetsFor(today: string): AsOfPreset[] {
  return [
    { label: 'Today', value: today },
    { label: '1Y ago', value: shiftYears(today, 1) },
    { label: '5Y ago', value: shiftYears(today, 5) },
    { label: '10Y ago', value: shiftYears(today, 10) },
  ];
}

export interface AsOfControlProps {
  value: string;
  onChange: (value: string) => void;
  /** Today, passed in so the control is deterministic under test. */
  today: string;
  /**
   * The date the server says it resolved to. Shown only when it differs from
   * the request — a silent substitution is the thing this screen exists to
   * prevent, so a loud one is the only acceptable kind.
   */
  resolved?: string | null;
}

/**
 * The control that makes this a point-in-time screen rather than a fact sheet.
 *
 * Everything below re-reads when this changes: the accounts resolve to filings
 * public on or before this date, and the price series is cut here too. The same
 * symbol on two dates is two different answers, and that is the point.
 */
export function AsOfControl({ value, onChange, today, resolved }: AsOfControlProps) {
  const inputId = useId();
  const presets = presetsFor(today);

  return (
    <div className="w-full min-w-0 lg:w-auto lg:shrink-0">
      <label
        htmlFor={inputId}
        className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
      >
        As of
      </label>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:flex-none">
          <CalendarDays
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            id={inputId}
            type="date"
            max={today}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            className={cn(fieldClasses, 'w-full pl-8 sm:w-44')}
          />
        </div>
        <ButtonGroup label="As-of presets" title="Move the as-of date back">
          {presets.map((preset) => (
            <button
              key={preset.label}
              type="button"
              aria-pressed={preset.value === value}
              onClick={() => onChange(preset.value)}
              className={cn(
                'h-11 rounded-sm border px-3 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors lg:h-9 lg:px-2',
                preset.value === value
                  ? 'border-primary text-primary'
                  : 'border-border text-muted-foreground hover:text-foreground',
              )}
            >
              {preset.label}
            </button>
          ))}
        </ButtonGroup>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {resolved && resolved !== value
          ? `Requested ${value}; the server resolved to ${resolved}.`
          : 'Accounts are read as they were on this date. Nothing filed after it is shown.'}
      </p>
    </div>
  );
}
