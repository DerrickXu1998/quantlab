import {
  forwardRef,
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type SelectHTMLAttributes,
} from 'react';
import { cn } from '../../lib/utils';

/**
 * The one field treatment, shared by every form in the app: square corners, a
 * 1px border, values in mono, and focus marked by the accent border — never a
 * shadow or a ring.
 */
// `h-11` on touch, `h-9` back at `lg`.
//
// One string, so every input, select and date field in the app gets a 44px
// target at once rather than each screen discovering it separately. `text-base`
// below `lg` is not cosmetic: iOS Safari zooms the page when a focused input's
// text is under 16px, and that zoom is what leaves a mobile form scrolled
// sideways with no way back. The 11px mono returns with the desktop row.
export const fieldClasses =
  'h-11 w-full rounded-sm border border-input bg-background px-2 font-mono text-base tabular-nums text-foreground transition-colors focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 lg:h-9 lg:text-[11px]';

export const Label = forwardRef<HTMLLabelElement, LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn(
        'flex flex-col gap-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground',
        className,
      )}
      {...props}
    />
  ),
);
Label.displayName = 'Label';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(fieldClasses, className)} {...props} />
  ),
);
Input.displayName = 'Input';

/**
 * A styled native <select>, deliberately not a Radix listbox: the existing filter
 * tests drive these with selectOptions() against the native combobox role, and
 * FR-010 requires that behavior stay identical through the restyle.
 */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select ref={ref} className={cn(fieldClasses, 'pr-8', className)} {...props} />
  ),
);
Select.displayName = 'Select';
