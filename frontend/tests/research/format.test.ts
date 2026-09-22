import { describe, expect, it } from 'vitest';
import {
  conceptLabel,
  formatCompact,
  formatCount,
  formatFactValue,
  formatMultiple,
  formatPercent,
  formatPrice,
  formatStaleness,
  formatTriggers,
  METRIC_FORMAT,
  NOT_APPLICABLE,
} from '../../src/research/format';

/**
 * The bug this file exists for.
 *
 * The signal table rendered `close=17.68000030517578, prior_min_low=
 * 17.829999923706055` — float64s printed at full precision. A table that does
 * that reads as debug output, and that judgement carries to every number
 * beside it (docs/RESEARCH.md §1e).
 */
describe('formatTriggers', () => {
  it('stops the seventeen-digit float dump that started this', () => {
    const [close, prior] = formatTriggers({
      close: 17.68000030517578,
      prior_min_low: 17.829999923706055,
    });

    expect(close).toEqual({ label: 'close', value: '17.68' });
    expect(prior).toEqual({ label: 'prior min low', value: '17.83' });
  });

  it('drops the rule prefix, which the row already names', () => {
    expect(formatTriggers({ 'pe-filter.pe_ratio': 11.62 })).toEqual([
      { label: 'pe ratio', value: '11.62' },
    ]);
  });

  it('scales a magnitude rather than printing its digits', () => {
    expect(formatTriggers({ volume: 67_060_000_000 })).toEqual([
      { label: 'volume', value: '67.1bn' },
    ]);
  });

  it('keeps an oscillator readable without pretending to know its unit', () => {
    expect(formatTriggers({ rsi: 34.999999 })).toEqual([{ label: 'rsi', value: '35.00' }]);
  });

  it('survives a non-numeric or absent trigger instead of rendering NaN', () => {
    expect(formatTriggers({ direction: 'bullish', missing: null })).toEqual([
      { label: 'direction', value: 'bullish' },
      { label: 'missing', value: NOT_APPLICABLE },
    ]);
  });

  it('answers nothing for no triggers', () => {
    expect(formatTriggers(null)).toEqual([]);
    expect(formatTriggers(undefined)).toEqual([]);
  });
});

/**
 * The rule the destination turns on: unknown is not zero. A missing book value
 * does not make a company cheap. Every formatter has to hold this line, so it
 * is asserted across all of them at once rather than one test per function.
 */
describe('absence is never a zero', () => {
  const formatters = {
    formatPrice,
    formatCompact,
    formatMultiple,
    formatPercent,
    formatCount,
  };

  for (const [name, format] of Object.entries(formatters)) {
    it(`${name} renders an em dash for null, undefined and NaN`, () => {
      for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
        expect(format(value as number | null)).toBe(NOT_APPLICABLE);
      }
      // And is not merely refusing everything: a real zero still reads as zero.
      expect(format(0)).not.toBe(NOT_APPLICABLE);
    });
  }

  it('holds for the derived metric renderers too', () => {
    for (const metric of Object.values(METRIC_FORMAT)) {
      expect(metric.render(null)).toBe(NOT_APPLICABLE);
    }
  });
});

describe('formatCompact', () => {
  it('reads CAT’s filed revenue as a fact rather than a counting exercise', () => {
    expect(formatCompact(67_060_000_000)).toBe('67.1bn');
  });

  it('holds three significant figures across the scales', () => {
    expect(formatCompact(671_000_000)).toBe('671m');
    expect(formatCompact(67_100_000)).toBe('67.1m');
    expect(formatCompact(6_710_000)).toBe('6.71m');
    expect(formatCompact(1_234)).toBe('1.23k');
  });

  it('keeps the sign on a negative, which is a real accounting figure', () => {
    expect(formatCompact(-5_535_000_000)).toBe('-5.54bn');
  });
});

describe('formatPrice', () => {
  it('keeps the cents that matter on a close', () => {
    expect(formatPrice(17.68000030517578)).toBe('17.68');
  });

  it('drops the cents that are noise at scale, and groups', () => {
    expect(formatPrice(67060)).toBe('67,060');
  });

  it('appends a currency only when told one', () => {
    expect(formatPrice(17.68, 'USD')).toBe('17.68 USD');
    expect(formatPrice(17.68)).toBe('17.68');
  });
});

describe('formatMultiple and formatPercent', () => {
  it('writes a P/E the way it is spoken', () => {
    expect(formatMultiple(11.62)).toBe('11.6×');
  });

  it('writes a held fraction as a percentage', () => {
    expect(formatPercent(0.1543)).toBe('15.4%');
  });
});

describe('formatFactValue', () => {
  it('never puts a currency beside a share count', () => {
    expect(formatFactValue('shares_outstanding', 492_000_000, 'shares')).toBe('492m sh');
  });

  it('carries the filed currency on a money figure', () => {
    expect(formatFactValue('revenue', 67_060_000_000, 'USD')).toBe('67.1bn USD');
  });

  it('shows no unit for a pure figure', () => {
    expect(formatFactValue('revenue', 67_060_000_000, 'pure')).toBe('67.1bn');
  });
});

describe('conceptLabel', () => {
  it('writes a column name the way an analyst says the line item', () => {
    expect(conceptLabel('operating_cash_flow')).toBe('Operating cash flow');
  });

  /**
   * 88.8% of the fundamentals table carries an unmapped concept. A figure the
   * UI does not recognise is still a real filed number, so it is shown
   * readably rather than hidden.
   */
  it('un-snakes an unmapped concept rather than dropping it', () => {
    expect(conceptLabel('retained_earnings')).toBe('Retained earnings');
  });
});

/**
 * Staleness decides whether a fundamental figure should be trusted at all —
 * the rules stop honouring one past 455 days — so it is written as a duration
 * the reader feels, not a date difference they compute.
 */
describe('formatStaleness', () => {
  it('reads in the units a person thinks in', () => {
    expect(formatStaleness(0)).toBe('today');
    expect(formatStaleness(1)).toBe('1 day ago');
    expect(formatStaleness(60)).toBe('60 days ago');
    expect(formatStaleness(135)).toBe('4 months ago');
  });

  it('crosses into years, where the staleness limit bites', () => {
    expect(formatStaleness(455)).toBe('1.2 years ago');
    expect(formatStaleness(900)).toBe('2 years ago');
  });

  it('renders an unknown staleness as unknown', () => {
    expect(formatStaleness(null)).toBe(NOT_APPLICABLE);
  });
});
