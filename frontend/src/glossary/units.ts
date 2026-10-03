import {
  BARS_PER_SESSION,
  isIntraday,
  type BarFrequency,
} from '../strategies/barFrequency';

/**
 * The units QuantLab's numbers are measured in, said once.
 *
 * Every term in the glossary names one of these, so "bars" means the same
 * thing on every tooltip, and the one unit that changes meaning with the bar
 * size -- bars -- is explained against the bar size actually in use.
 */
export type UnitKind =
  | 'bars'
  | 'trading-days'
  | 'calendar-days'
  | 'percent'
  | 'percent-of-price'
  | 'fraction'
  | 'percentage-points'
  | 'basis-points'
  | 'ratio'
  | 'level-0-100'
  | 'std-devs'
  | 'atr-multiple'
  | 'multiple'
  | 'count'
  | 'currency'
  | 'on-off'
  | 'choice'
  | 'annualised-ratio'
  | 'index-level';

/** "5-minute bars", as an adjective. */
const BAR_SIZE: Record<BarFrequency, string> = {
  '1d': 'daily',
  '1h': '1-hour',
  '15m': '15-minute',
  '5m': '5-minute',
};

/** Minutes in one bar, for turning a bar count into time. */
const MINUTES_PER_BAR: Record<BarFrequency, number> = { '1d': 390, '1h': 60, '15m': 15, '5m': 5 };

function duration(minutes: number): string {
  if (minutes < 120) return `${Math.round(minutes)} min`;
  const hours = minutes / 60;
  if (hours < 6.5 * 2) return `${Number(hours.toFixed(1))} h`;
  return `${Number((minutes / 390).toFixed(1))} sessions`;
}

/** "14 bars ≈ 70 min on 5-minute bars": a bar count as time, for this bar size. */
export function barsAsTime(count: number, frequency: BarFrequency): string {
  if (!isIntraday(frequency)) return `${count} trading day${count === 1 ? '' : 's'}`;
  return `≈ ${duration(count * MINUTES_PER_BAR[frequency])}`;
}

/**
 * The unit line of a tooltip. `example` is the value on screen, when there is
 * one, so a bar count can be read back as time.
 */
export function describeUnit(
  unit: UnitKind,
  frequency: BarFrequency,
  example?: number | null,
): string {
  switch (unit) {
    case 'bars': {
      const per = BARS_PER_SESSION[frequency];
      const base = isIntraday(frequency)
        ? `Bars of the run's bar size: here ${BAR_SIZE[frequency]} bars, ${per} a session.`
        : 'Bars of the run’s bar size: here daily bars, one a trading day.';
      return example != null && Number.isFinite(example)
        ? `${base} ${example} bars ${isIntraday(frequency) ? barsAsTime(example, frequency) : `= ${barsAsTime(example, frequency)}`}.`
        : base;
    }
    case 'trading-days':
      return 'Trading days, at every bar size: on 5-minute bars, 1 means the next session, never the next bar.';
    case 'calendar-days':
      return 'Calendar days, weekends included.';
    case 'percent':
      return 'A percentage: 12 means 12%.';
    case 'percent-of-price':
      return 'Percent of the price: 8 means the price moved 8% from where it is measured.';
    case 'fraction':
      return 'A fraction: 0.10 is 10%.';
    case 'percentage-points':
      return 'Percentage points of the series itself: a spread moving from 3.0 to 3.5 is 0.5 points.';
    case 'basis-points':
      return 'Basis points: 1 bp is 0.01%, so 5 bps on $10,000 is $5.';
    case 'ratio':
      return 'A plain ratio of two quantities, no unit.';
    case 'level-0-100':
      return 'An oscillator level on a 0 to 100 scale.';
    case 'std-devs':
      return 'Standard deviations of the price over the window.';
    case 'atr-multiple':
      return 'Multiples of the Average True Range: 2 means twice the typical bar-to-bar range.';
    case 'multiple':
      return 'A multiple of the average: 2 means twice it.';
    case 'count':
      return 'A whole-number count.';
    case 'currency':
      return 'US dollars.';
    case 'on-off':
      return 'On or off.';
    case 'choice':
      return 'One of a fixed set of choices.';
    case 'annualised-ratio':
      return 'A ratio, annualised: comparable across windows of different length.';
    case 'index-level':
      return 'The level of the index itself, in its own points.';
    default:
      return '';
  }
}
