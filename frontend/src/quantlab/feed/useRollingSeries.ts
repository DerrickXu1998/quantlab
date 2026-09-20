import { useEffect, useState } from 'react';
import { useTick } from './FeedProvider';

/** How many ticks the indicator charts keep. */
export const SERIES_LENGTH = 240;

/**
 * The rolling intraday series behind the Indicators view.
 *
 * The feed itself remembers only a sparkline's worth of points, so the view
 * accumulates its own: one appended price per tick, bounded, reset when the
 * symbol changes. The first points come from the tick's own history — the
 * walk's seed is the real last close, so the series starts plausible and stays
 * invented.
 */
export function useRollingSeries(symbol: string | null, maxLength = SERIES_LENGTH): number[] {
  const tick = useTick(symbol ?? '');
  const [series, setSeries] = useState<number[]>([]);

  useEffect(() => {
    setSeries([]);
  }, [symbol]);

  useEffect(() => {
    if (!tick) return;
    setSeries((current) => {
      if (current.length === 0) return tick.history.slice(-maxLength);
      if (current[current.length - 1] === tick.price) return current;
      return [...current, tick.price].slice(-maxLength);
    });
  }, [tick, maxLength]);

  return series;
}
