import {
  forwardRef,
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type SelectHTMLAttributes,
} from 'react';
import { cn } from '../../lib/utils';

const controlClasses =
  'h-9 rounded-md border border-input bg-card px-2 text-sm text-foreground shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50';

export const Label = forwardRef<HTMLLabelElement, LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn('flex flex-col gap-1 text-xs font-semibold text-muted-foreground', className)}
      {...props}
    />
  ),
);
Label.displayName = 'Label';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(controlClasses, className)} {...props} />
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
    <select ref={ref} className={cn(controlClasses, 'pr-8', className)} {...props} />
  ),
);
Select.displayName = 'Select';
