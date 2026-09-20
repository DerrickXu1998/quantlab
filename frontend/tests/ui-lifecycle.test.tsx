import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LifecycleBadge, LifecycleRow } from '../src/components/ui/lifecycle';

/**
 * The lifecycle vocabulary had been written twice — inline in `ModelList` and
 * again in the strategy library — with the same reasoning in both docstrings
 * and no shared code. These tests guard the consolidated version, and in
 * particular the one property that makes it safety-critical rather than
 * decorative.
 */
describe('LifecycleBadge', () => {
  it('lights the states this build can actually reach', () => {
    render(<LifecycleBadge state="backtest" testId="b" />);
    const badge = screen.getByTestId('b');
    expect(badge).toHaveTextContent(/backtest/i);
    expect(badge.className).toContain('text-primary');
  });

  it('never lights LIVE or PAPER, whatever it is asked for', () => {
    // A lit LIVE chip asserts that real money is moving. There is no broker
    // behind this build, so no argument to this component may produce one.
    for (const state of ['live', 'paper'] as const) {
      const { unmount } = render(<LifecycleBadge state={state} active testId="b" />);
      const badge = screen.getByTestId('b');
      expect(badge.className).toContain('text-muted-foreground/50');
      expect(badge.className).not.toContain('text-primary');
      expect(badge.getAttribute('title')).toMatch(/no execution backend/i);
      unmount();
    }
  });

  it('dims a reachable state that is not the current one', () => {
    render(<LifecycleBadge state="backtest" active={false} testId="b" />);
    expect(screen.getByTestId('b').className).toContain('text-muted-foreground/50');
  });
});

describe('LifecycleRow', () => {
  it('shows the whole vocabulary with only backtest lit', () => {
    render(<LifecycleRow />);
    // Saying "these are the modes, and this is the one you are in" is more
    // honest than hiding the two that do not exist.
    for (const label of [/backtest/i, /paper/i, /live/i]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText(/backtest/i).className).toContain('text-primary');
    expect(screen.getByText(/live/i).className).not.toContain('text-primary');
  });
});
