import { describe, expect, it } from 'vitest';
import {
  describeConstraint,
  echoBound,
  isFraction,
  newDraft,
  readDrafts,
} from '../../../src/research/screen/constraints';

describe('readDrafts', () => {
  it('sends an unset bound as null, never as a zero', () => {
    // The distinction the whole destination turns on. A P/E floor of "none"
    // and a P/E floor of 0 are different questions, and the second one
    // silently excludes every loss-making company.
    const draft = { ...newDraft('pe'), max: '15' };

    const { constraints, errors } = readDrafts([draft]);

    expect(errors).toEqual({});
    expect(constraints).toEqual([{ metric: 'pe', min: null, max: 15 }]);
  });

  it('refuses a constraint with no bounds at all rather than sending an empty one', () => {
    const draft = newDraft('roe');

    const { constraints, errors } = readDrafts([draft]);

    expect(constraints).toEqual([]);
    expect(errors[draft.id]).toMatch(/minimum, a maximum, or both/i);
  });

  it('refuses a bound that is not a number instead of quietly dropping it', () => {
    // Dropping it would widen the screen past what the user asked for and
    // report the extra names as though they had qualified.
    const draft = { ...newDraft('roe'), min: 'twelve' };

    const { constraints, errors } = readDrafts([draft]);

    expect(constraints).toEqual([]);
    expect(errors[draft.id]).toMatch(/must be numbers/i);
  });

  it('catches an inverted range, which can never match anything', () => {
    const draft = { ...newDraft('pe'), min: '30', max: '10' };

    const { errors } = readDrafts([draft]);

    expect(errors[draft.id]).toMatch(/minimum is above the maximum/i);
  });

  it('refuses a second constraint on the same metric', () => {
    const first = { ...newDraft('pe'), max: '15' };
    const second = { ...newDraft('pe'), min: '5' };

    const { constraints, errors } = readDrafts([first, second]);

    expect(constraints).toHaveLength(1);
    expect(errors[second.id]).toMatch(/already constrained/i);
  });
});

describe('units', () => {
  it('names the fractional metrics, and echoes a typed bound back formatted', () => {
    // 0.12 is 12%. The app must never guess that a typed `12` meant 12% and
    // divide it by 100 behind the user's back.
    expect(isFraction('roe')).toBe(true);
    expect(isFraction('gross_margin')).toBe(true);
    expect(isFraction('pe')).toBe(false);

    expect(echoBound('roe', '0.12')).toBe('12.0%');
    expect(echoBound('pe', '15')).toBe('15.0×');
    expect(echoBound('pe', '')).toBeNull();
  });
});

describe('describeConstraint', () => {
  it('reads back as a sentence, in the metric’s own unit', () => {
    expect(describeConstraint({ metric: 'pe', min: null, max: 15 })).toBe('P/E at most 15.0×');
    expect(describeConstraint({ metric: 'roe', min: 0.15, max: null })).toBe(
      'ROE at least 15.0%',
    );
    expect(describeConstraint({ metric: 'leverage', min: 0.2, max: 0.8 })).toBe(
      'Leverage 0.20 to 0.80',
    );
  });
});
