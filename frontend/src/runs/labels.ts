import type { Run } from '../api/client';

/**
 * What a run is called everywhere runs are listed. A saved run keeps its
 * name; an unsaved strategy run falls back to the strategy's own name rather
 * than `model_name`, which the backend fills with the first entry component
 * for legacy clients — showing it would disguise a strategy as a signal run.
 * Legacy single-model runs are unaffected: their promoted spec's name is the
 * model name anyway.
 */
export function runDisplayName(run: Run): string {
  return run.name ?? run.strategy?.name ?? run.model_name;
}
