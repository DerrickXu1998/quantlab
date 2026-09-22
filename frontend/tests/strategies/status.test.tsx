import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  StrategyStatusBadge,
  executedStrategyNames,
  statusOf,
} from '../../src/strategies/StrategyStatus';

describe('executedStrategyNames', () => {
  it('reads the name off the spec a run recorded, not its model_name', () => {
    // The trap this exists to avoid: a composed run reports `model_name` as
    // its first entry component, so "RSI mean reversion" surfaces as
    // "rsi-threshold" and matching on it leaves every strategy a draft.
    const runs = [
      { model_name: 'rsi-threshold', strategy: { name: 'RSI mean reversion' } },
      { model_name: 'macd-crossover', strategy: { name: 'MACD trend' } },
    ];
    expect(executedStrategyNames(runs)).toEqual(
      new Set(['RSI mean reversion', 'MACD trend']),
    );
  });

  it('ignores runs that predate strategies', () => {
    // A single-model run has no spec and belongs to no saved strategy.
    expect(executedStrategyNames([{ model_name: 'rsi-threshold' }])).toEqual(new Set());
    expect(executedStrategyNames([{ strategy: null }])).toEqual(new Set());
  });
});

describe('statusOf', () => {
  it('is backtest once the strategy has been run, and a draft before', () => {
    const executed = new Set(['RSI mean reversion']);
    expect(statusOf('RSI mean reversion', executed)).toBe('backtest');
    expect(statusOf('MACD trend', executed)).toBe('draft');
  });
});

describe('StrategyStatusBadge', () => {
  it('shows a run strategy as backtest, and says no money moved', () => {
    render(<StrategyStatusBadge status="backtest" testId="s" />);
    const badge = screen.getByTestId('s');
    expect(badge).toHaveTextContent(/backtest/i);
    expect(badge.getAttribute('title')).toMatch(/no money.*has moved/i);
  });

  it('never presents live or paper as reachable in a build that cannot trade', () => {
    // The most consequential label a trading surface can show. If this ever
    // renders as an active state, the app is asserting that real money is
    // moving through a system that has no broker behind it.
    for (const status of ['live', 'paper'] as const) {
      const { unmount } = render(<StrategyStatusBadge status={status} testId="s" />);
      const badge = screen.getByTestId('s');
      expect(badge.getAttribute('title')).toMatch(/no execution backend/i);
      // The 'disabled' tone, which the design system reserves for a capability
      // that does not exist.
      expect(badge.className).toMatch(/text-muted-foreground\/50/);
      expect(badge.className).not.toMatch(/text-primary/);
      unmount();
    }
  });

  it('still renders the live and paper vocabulary, ready for a backend', () => {
    render(<StrategyStatusBadge status="live" testId="s" />);
    expect(screen.getByTestId('s')).toHaveTextContent(/live/i);
  });
});
