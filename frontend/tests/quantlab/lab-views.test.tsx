import { describe, expect, it } from 'vitest';
import { bollinger, lastValue, macd, rsi, vwap } from '../../src/quantlab/data/indicators';

describe('indicator math', () => {
  it('pads with null until the warmup is done, never a zero', () => {
    const values = Array.from({ length: 20 }, (_, i) => 100 + i);

    const result = rsi(values, 14);

    expect(result).toHaveLength(20);
    expect(result.slice(0, 14).every((value) => value === null)).toBe(true);
    expect(lastValue(result)).not.toBeNull();
  });

  it('reads 100 on a series that only rises', () => {
    const values = Array.from({ length: 30 }, (_, i) => 100 + i);

    expect(lastValue(rsi(values))).toBeCloseTo(100, 6);
  });

  it('puts the Bollinger mid on the SMA and the bands symmetric around it', () => {
    const values = Array.from({ length: 25 }, (_, i) => 100 + Math.sin(i) * 5);

    const bands = bollinger(values, 20, 2);
    const last = bands[bands.length - 1];

    const sma = values.slice(-20).reduce((a, b) => a + b, 0) / 20;
    expect(last.mid).toBeCloseTo(sma, 10);
    expect(last.upper! - last.mid!).toBeCloseTo(last.mid! - last.lower!, 10);
    expect(bands[0].mid).toBeNull();
  });

  it('keeps the MACD histogram as line minus signal', () => {
    const values = Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 3) * 10);

    const result = macd(values);
    const index = values.length - 1;

    expect(result.histogram[index]).toBeCloseTo(
      (result.line[index] as number) - (result.signal[index] as number),
      10,
    );
  });

  it('computes VWAP as the cumulative mean of the series', () => {
    const result = vwap([10, 20, 30]);

    expect(result).toEqual([10, 15, 20]);
  });
});
