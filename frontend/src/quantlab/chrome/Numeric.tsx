import { cn } from '../../lib/utils';

export type NumericTone = 'default' | 'signed' | 'accent' | 'muted';

export interface NumericProps {
  value: number | null | undefined;
  /** 'price' | 'percent' | 'signed-percent' | 'ratio' | 'integer' */
  format?: 'price' | 'percent' | 'signedPercent' | 'ratio' | 'integer' | 'currency';
  tone?: NumericTone;
  className?: string;
}

/** An unmeasurable value is a dash, never a zero. */
const ABSENT = '—';

export function formatNumeric(value: number, format: NumericProps['format']): string {
  switch (format) {
    case 'percent':
      return `${(value * 100).toFixed(2)}%`;
    case 'signedPercent':
      return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
    case 'ratio':
      return value.toFixed(2);
    case 'integer':
      return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
    case 'currency':
      return value.toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 0,
      });
    case 'price':
    default:
      return value.toFixed(2);
  }
}

/**
 * Every number on this surface renders through here: mono, tabular-nums, so
 * columns of figures line up and a changing digit does not shift the ones
 * beside it.
 *
 * `signed` is the only tone allowed to use --destructive — red means a loss or
 * a drawdown here, never an error.
 */
export function Numeric({ value, format = 'price', tone = 'default', className }: NumericProps) {
  const absent = value === null || value === undefined || !Number.isFinite(value);
  const signedTone = !absent && tone === 'signed' ? (value >= 0 ? 'up' : 'down') : null;

  return (
    <span
      className={cn(
        'font-mono tabular-nums',
        tone === 'accent' && 'text-primary',
        tone === 'muted' && 'text-muted-foreground',
        signedTone === 'up' && 'text-primary',
        signedTone === 'down' && 'text-destructive',
        absent && 'text-muted-foreground',
        className,
      )}
    >
      {absent ? ABSENT : formatNumeric(value, format)}
    </span>
  );
}
