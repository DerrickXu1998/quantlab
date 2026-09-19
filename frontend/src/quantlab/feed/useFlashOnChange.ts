import { useEffect, useRef, useState } from 'react';

export const FLASH_MS = 400;

/**
 * True for 400ms after `value` changes.
 *
 * This is the surface's only continuous animation, and it is a CSS transition
 * rather than a keyframe loop — nothing animates while the value is still.
 * The first render does not flash: arriving is not changing.
 */
export function useFlashOnChange(value: unknown, durationMs = FLASH_MS): boolean {
  const [flashing, setFlashing] = useState(false);
  const previous = useRef(value);

  useEffect(() => {
    if (Object.is(previous.current, value)) return;
    previous.current = value;
    setFlashing(true);
    const timer = window.setTimeout(() => setFlashing(false), durationMs);
    return () => window.clearTimeout(timer);
  }, [value, durationMs]);

  return flashing;
}
