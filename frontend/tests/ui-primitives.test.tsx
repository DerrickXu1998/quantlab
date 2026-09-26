import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button } from '../src/components/ui/button';
import { formatNumeric, Numeric } from '../src/components/ui/numeric';
import { StatusBadge } from '../src/components/ui/status-badge';

describe('Button', () => {
  it('follows the terminal grammar: square, hairline, mono uppercase label', () => {
    render(<Button>Run backtest</Button>);

    const button = screen.getByRole('button', { name: /run backtest/i });
    expect(button).toHaveClass(
      'rounded-sm',
      'border',
      'font-mono',
      'uppercase',
      'tracking-[0.12em]',
    );
    expect(button.className).not.toMatch(/rounded-(md|lg|full)|shadow-/);
  });

  it('renders the primary action in the accent and nothing else', () => {
    render(
      <div>
        <Button>Primary</Button>
        <Button variant="outline">Outline</Button>
        <Button variant="ghost">Ghost</Button>
      </div>,
    );

    expect(screen.getByRole('button', { name: 'Primary' })).toHaveClass(
      'bg-primary',
      'text-primary-foreground',
    );
    for (const name of ['Outline', 'Ghost']) {
      expect(screen.getByRole('button', { name })).not.toHaveClass('bg-primary');
    }
  });
});

describe('Numeric', () => {
  it('formats with mono tabular figures so columns line up', () => {
    render(<Numeric value={1234.5} format="price" />);

    const value = screen.getByText('1234.50');
    expect(value).toHaveClass('font-mono', 'tabular-nums');
  });

  it('renders an unmeasurable value as a dash, never a zero', () => {
    render(<Numeric value={null} format="percent" />);

    expect(screen.getByText('—')).toHaveClass('text-muted-foreground');
  });

  it('reserves red for losses: a negative signed value, and only that, is destructive', () => {
    render(
      <div>
        <Numeric value={-0.07} format="signedPercent" tone="signed" />
        <Numeric value={0.12} format="signedPercent" tone="signed" />
      </div>,
    );

    expect(screen.getByText('-7.00%')).toHaveClass('text-destructive');
    expect(screen.getByText('+12.00%')).toHaveClass('text-primary');
    expect(screen.getByText('+12.00%')).not.toHaveClass('text-destructive');
  });

  it('keeps formatNumeric stable for the canvas charts that share it', () => {
    expect(formatNumeric(100000, 'currency')).toBe('$100,000');
    expect(formatNumeric(0.6, 'percent')).toBe('60.00%');
    expect(formatNumeric(1.84, 'ratio')).toBe('1.84');
  });
});

describe('StatusBadge', () => {
  it('uses the canonical mono uppercase label spec in every tone', () => {
    render(<StatusBadge tone="active">Live</StatusBadge>);

    expect(screen.getByText('Live')).toHaveClass(
      'rounded-sm',
      'font-mono',
      'text-[11px]',
      'uppercase',
      'tracking-[0.12em]',
    );
  });

  it('absorbed the simulated tag as a tone, with the reason on hover', () => {
    render(
      <StatusBadge tone="simulated" title="Invented numbers" testId="simulated-tag">
        Simulated
      </StatusBadge>,
    );

    const tag = screen.getByTestId('simulated-tag');
    expect(tag).toHaveTextContent(/simulated/i);
    expect(tag).toHaveAttribute('title', 'Invented numbers');
  });
});
