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
export const fieldClasses =
  'h-9 w-full rounded-sm border border-input bg-background px-2 font-mono text-[11px] tabular-nums text-foreground transition-colors focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50';

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
