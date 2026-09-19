import { cn } from '../../lib/utils';
import { useFlashOnChange } from '../feed/useFlashOnChange';
import { Numeric, type NumericProps } from './Numeric';

/**
 * A number that flashes the accent for 400ms when it moves.
 *
 * The flash is the *only* thing on this surface that animates continuously,
 * and only while data is actually arriving.
 */
export function FlashNumber({ className, ...props }: NumericProps) {
  const flashing = useFlashOnChange(props.value);

  return (
    <span
      data-flash={flashing ? 'on' : undefined}
      className={cn(
        'inline-block rounded-sm px-1 transition-colors duration-200',
        flashing && 'bg-primary/15',
        className,
      )}
    >
      <Numeric {...props} />
    </span>
  );
}
