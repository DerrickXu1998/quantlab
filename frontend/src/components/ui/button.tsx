import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

/**
 * The one button. Terminal grammar: square corners, a 1px border, a mono
 * uppercase label, and the accent reserved for the primary action.
 */
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-sm border font-mono text-[11px] uppercase tracking-[0.12em] transition-colors focus-visible:outline-none focus-visible:border-primary disabled:cursor-not-allowed',
  {
    variants: {
      variant: {
        default:
          'border-primary bg-primary text-primary-foreground hover:bg-primary/90 disabled:border-border disabled:bg-transparent disabled:text-muted-foreground',
        outline:
          'border-border bg-card text-foreground hover:border-primary/50 hover:text-primary disabled:opacity-40',
        ghost: 'border-transparent text-muted-foreground hover:text-foreground disabled:opacity-40',
      },
      // Touch first, then the dense desktop row back at `lg`.
      //
      // A 28px control is comfortable with a mouse and unreliable with a
      // thumb; 44px is the floor a finger hits. The desktop heights are not
      // changed -- they return at `lg`, so the terminal stays as tight as it
      // was on the screens it was designed for. Horizontal padding grows with
      // the height so the proportions hold rather than the label rattling
      // inside a tall box.
      size: {
        default: 'h-11 px-4 lg:h-8 lg:px-3',
        sm: 'h-11 px-3.5 lg:h-7 lg:px-2.5',
        icon: 'h-11 w-11 lg:h-8 lg:w-8',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
    );
  },
);
Button.displayName = 'Button';

export { buttonVariants };
