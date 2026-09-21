import { LifecycleBadge, type Lifecycle } from '../components/ui/lifecycle';

/**
 * A strategy's place in its lifecycle, and the badge for it.
 *
 * The vocabulary, the presentation and — critically — the rule that LIVE and
 * PAPER never render as reachable in a build with no broker all live in
 * `components/ui/lifecycle`. This module is the strategy-shaped view of it:
 * how a *saved strategy* earns its state from the run history.
 */
export type StrategyStatus = Lifecycle;

export function StrategyStatusBadge({
  status,
  testId,
}: {
  status: StrategyStatus;
  testId?: string;
}) {
  return <LifecycleBadge state={status} testId={testId} />;
}

/**
 * A strategy's status, from what is actually known about it.
 *
 * Derived rather than stored: "has this been run" is a fact about the run
 * history, and a status column on the strategy row would be a second copy of
 * it that goes stale the moment a run is deleted.
 *
 * The names to match against are the *strategies runs recorded*, not their
 * `model_name`. A composed run reports `model_name` as its first entry
 * component — `rsi-threshold` for a strategy called "RSI mean reversion" — so
 * matching on that would have left every strategy permanently a draft.
 * `executedStrategyNames` below is the correct source.
 */
export function statusOf(
  strategyName: string,
  executedNames: ReadonlySet<string>,
): StrategyStatus {
  return executedNames.has(strategyName) ? 'backtest' : 'draft';
}

/**
 * The names of the strategies that have actually been run.
 *
 * A run carries the resolved spec it executed, and that spec's name is the
 * strategy's own. Runs recorded before strategies existed have no spec and
 * contribute nothing, which is correct — they were single-model runs and
 * belong to no saved strategy.
 */
export function executedStrategyNames(
  // Deliberately open: a real `Run` carries twenty other fields, and a
  // parameter type listing only the one this reads makes every caller — and
  // every fixture — fail TypeScript's excess-property check for passing a
  // genuine run.
  runs: readonly { strategy?: { name?: string } | null; [key: string]: unknown }[],
): ReadonlySet<string> {
  const names = new Set<string>();
  for (const run of runs) {
    const name = run.strategy?.name;
    if (name) names.add(name);
  }
  return names;
}
