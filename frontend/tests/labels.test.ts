import { describe, expect, it } from 'vitest';
import type { Run } from '../src/api/client';
import { runDisplayName } from '../src/runs/labels';

function makeRun(overrides: Partial<Run>): Run {
  return { model_name: 'stochastic-threshold', ...overrides } as Run;
}

describe('runDisplayName', () => {
  it('prefers the saved run name above everything', () => {
    const run = makeRun({
      name: 'my experiment',
      strategy: { name: 'A1 trend pullback' } as Run['strategy'],
    });
    expect(runDisplayName(run)).toBe('my experiment');
  });

  it('falls back to the strategy name, not the legacy first-component model_name', () => {
    const run = makeRun({
      name: null,
      strategy: { name: 'A1 trend pullback' } as Run['strategy'],
    });
    expect(runDisplayName(run)).toBe('A1 trend pullback');
  });

  it('falls back to model_name for signal runs with no strategy', () => {
    const run = makeRun({ name: null, strategy: null });
    expect(runDisplayName(run)).toBe('stochastic-threshold');
  });
});
