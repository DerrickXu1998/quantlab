import { describe, expect, it } from 'vitest';
import {
  MAX_INTRADAY_BARS,
  MINUTE_DATA_START,
  runSize,
  weekdaysBetween,
} from '../../src/strategies/barFrequency';

describe('bar frequency arithmetic', () => {
  it('counts weekdays, both ends included', () => {
    expect(weekdaysBetween('2024-01-01', '2024-01-07')).toBe(5); // Mon..Sun
    expect(weekdaysBetween('2024-01-06', '2024-01-07')).toBe(0); // a weekend
    expect(weekdaysBetween('2024-01-08', '2024-01-01')).toBe(0); // backwards
  });

  it('sizes an intraday run as symbols x sessions x bars per session', () => {
    const size = runSize(2, '2024-01-01', '2024-01-07', '5m');
    expect(size.bars).toBe(2 * 5 * 78);
    expect(size.seconds).toBe(1);
    expect(size.blocker).toBeNull();
  });

  it('refuses an intraday run past the bar limit, the way the backend would', () => {
    // 400 symbols x a year of 5m bars is ~7.9M bars.
    const size = runSize(400, '2024-01-01', '2024-12-31', '5m');
    expect(size.bars).toBeGreaterThan(MAX_INTRADAY_BARS);
    expect(size.blocker).toMatch(/exceeds the limit of 6,000,000/);
  });

  it('refuses intraday bars before the minute data starts', () => {
    expect(runSize(1, '2016-06-01', '2017-06-01', '1h').blocker).toMatch(MINUTE_DATA_START);
  });

  it('leaves a full-universe daily run alone, with no time estimate', () => {
    const size = runSize(503, '2016-10-03', '2026-09-25', '1d');
    expect(size.blocker).toBeNull();
    expect(size.seconds).toBeNull();
  });
});
