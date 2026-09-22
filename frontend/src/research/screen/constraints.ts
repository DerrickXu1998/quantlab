import type { ScreenConstraint, ScreenMetric } from '../../api/types';
import { METRIC_FORMAT } from '../format';

/**
 * A constraint while it is being typed.
 *
 * Bounds are held as strings, not numbers, because a half-typed `0.` and an
 * empty box are different states and `parseFloat` flattens both to something
 * that is not what the user meant. They become numbers once, at submit.
 */
export interface ConstraintDraft {
  id: string;
  metric: ScreenMetric;
  min: string;
  max: string;
}

let counter = 0;

export function newDraft(metric: ScreenMetric): ConstraintDraft {
  counter += 1;
  return { id: `constraint-${counter}`, metric, min: '', max: '' };
}

/**
 * Bounds go over in the metric's own unit, and the UI says which that is.
 *
 * `roe`, `net_margin` and `gross_margin` are fractions — 0.12 is 12% — and the
 * single worst thing this form could do is guess. Typing `12` into an ROE
 * floor and having the app silently divide by 100 is the failure mode the
 * contract already warns about for parameter units (api/types.ts §2), so the
 * value is sent exactly as typed and echoed back formatted so the user can see
 * what the number they typed actually means.
 */
export function isFraction(metric: ScreenMetric): boolean {
  return metric === 'roe' || metric === 'net_margin' || metric === 'gross_margin';
}

/** What a typed bound means, written out. Empty is unbounded, not zero. */
export function echoBound(metric: ScreenMetric, raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return null;
  return METRIC_FORMAT[metric].render(value);
}

export interface DraftErrors {
  [draftId: string]: string;
}

export interface ReadDrafts {
  constraints: ScreenConstraint[];
  errors: DraftErrors;
}

function bound(raw: string): { ok: true; value: number | null } | { ok: false } {
  const trimmed = raw.trim();
  if (trimmed === '') return { ok: true, value: null };
  const value = Number(trimmed);
  return Number.isFinite(value) ? { ok: true, value } : { ok: false };
}

/**
 * Turn the drafts into the contract's shape, or say why they cannot be.
 *
 * Errors are returned rather than thrown so the form can mark the offending
 * row and keep the rest of the screen usable. A screen never runs with a
 * partial constraint set: a bound that failed to parse and a bound that was
 * never set would produce different answers, and silently dropping the first
 * would return a wider result than the user asked for.
 */
export function readDrafts(drafts: ConstraintDraft[]): ReadDrafts {
  const constraints: ScreenConstraint[] = [];
  const errors: DraftErrors = {};
  const seen = new Set<ScreenMetric>();

  for (const draft of drafts) {
    if (seen.has(draft.metric)) {
      errors[draft.id] = `${METRIC_FORMAT[draft.metric].label} is already constrained above.`;
      continue;
    }
    seen.add(draft.metric);

    const min = bound(draft.min);
    const max = bound(draft.max);
    if (!min.ok || !max.ok) {
      errors[draft.id] = 'Bounds must be numbers.';
      continue;
    }
    if (min.value === null && max.value === null) {
      errors[draft.id] = 'Set a minimum, a maximum, or both.';
      continue;
    }
    if (min.value !== null && max.value !== null && min.value > max.value) {
      errors[draft.id] = 'The minimum is above the maximum, so nothing can pass.';
      continue;
    }
    constraints.push({ metric: draft.metric, min: min.value, max: max.value });
  }

  return { constraints, errors };
}

/** How a constraint reads back as a sentence, for the results header. */
export function describeConstraint(constraint: ScreenConstraint): string {
  const { label, render } = METRIC_FORMAT[constraint.metric];
  const hasMin = constraint.min !== null && constraint.min !== undefined;
  const hasMax = constraint.max !== null && constraint.max !== undefined;
  if (hasMin && hasMax) return `${label} ${render(constraint.min)} to ${render(constraint.max)}`;
  if (hasMin) return `${label} at least ${render(constraint.min)}`;
  if (hasMax) return `${label} at most ${render(constraint.max)}`;
  return `${label} measured`;
}
