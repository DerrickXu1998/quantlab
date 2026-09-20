import { cn } from '../../lib/utils';
import { useFlashOnChange } from '../feed/useFlashOnChange';
import { Numeric, type NumericProps } from './Numeric';

/**
 * A number that flashes when it moves, for 400ms, and is otherwise still.
 *
 * This is the surface's only continuous animation, and it runs only while data
 * is actually arriving. It is a transition off a toggled class rather than a
 * keyframe loop, so a still value costs nothing.
 *
 * **Which colour it flashes.** Two rules in the design system meet here and
 * have to be reconciled rather than applied blindly: numbers flash the accent,
 * and #FF4D4D is reserved strictly for losses. Flashing a losing P&L acid lime
 * would satisfy the first and break the second — for 400ms the screen would
 * say "up" about a number that is down, which on a trading surface is the one
 * mistake that actually costs money.
 *
 * So the flash *intensifies the number's own meaning*: a neutral value (a
 * price, a size, a timestamp) flashes accent, and a signed value flashes the
 * colour it already carries — accent for a gain, destructive for a loss. The
 * accent remains the only non-semantic highlight on the surface, and red still
 * appears only against a loss.
 */
export function FlashNumber({ className, ...props }: NumericProps) {
  const flashing = useFlashOnChange(props.value);

  // Mirrors Numeric's own resolution, so the flash can never disagree with the
  // colour the number settles back to.
  const value = props.value;
  const measurable = value !== null && value !== undefined && Number.isFinite(value);
  const losing = measurable && props.tone === 'signed' && (value as number) < 0;

  return (
    <span
      data-flash={flashing ? 'on' : undefined}
      className={cn(
        'inline-block rounded-sm px-1 transition-colors duration-200',
        flashing && (losing ? 'bg-destructive/15' : 'bg-primary/15'),
        // The number itself takes the colour, not just the ground behind it.
        flashing && (losing ? '[&_*]:text-destructive' : '[&_*]:text-primary'),
        className,
      )}
    >
      <Numeric {...props} />
    </span>
  );
}
