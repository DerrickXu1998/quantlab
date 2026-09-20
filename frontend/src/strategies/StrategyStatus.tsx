import { StatusBadge } from '../components/ui/status-badge';

/**
 * Where a strategy sits in its lifecycle.
 *
 * Three states, in increasing order of consequence: it has been measured
 * against history, it is trading notional money forward, it is trading real
 * money. `draft` is the fourth, and is simply "none of those yet".
 */
export type StrategyStatus = 'draft' | 'backtest' | 'paper' | 'live';

/**
 * QuantLab executes backtests. It has no paper-trading engine and no broker
 * connection, so no strategy in this build can honestly be either of the top
 * two — and the badge says so rather than going quiet about it.
 *
 * This is the one place in the app where a decorative choice would be a
 * genuine hazard. A LIVE chip is the single most consequential label a trading
 * surface can show: it asserts that real money is moving. Rendering one
 * because it looks right on a dark terminal would be the same class of
 * mistake as flashing a losing position lime — a pixel that contradicts the
 * state of the book. The rest of the surface is already careful about this
 * (`SIM` in the nav, `SIMULATED` on invented numbers, `DEMO DATA` by the
 * dataset), and this follows the same rule.
 *
 * So `paper` and `live` are implemented, styled and ready for the day there is
 * an execution backend behind them; until then nothing returns them, and the
 * catalogue renders them plainly off.
 */
const PRESENTATION: Record<
  StrategyStatus,
  { label: string; tone: 'idle' | 'active' | 'good' | 'disabled'; title: string }
> = {
  draft: {
    label: 'Draft',
    tone: 'idle',
    title: 'Saved, but never run. Run it to see how it behaved over history.',
  },
  backtest: {
    label: 'Backtest',
    tone: 'good',
    title: 'Measured against stored history. No money, real or notional, has moved.',
  },
  paper: {
    label: 'Paper',
    tone: 'active',
    title: 'Trading notional money against a forward feed.',
  },
  live: {
    label: 'Live',
    tone: 'active',
    title: 'Trading real money through a broker.',
  },
};

/** Statuses this build can actually reach. */
export const SUPPORTED_STATUSES: readonly StrategyStatus[] = ['draft', 'backtest'];

export function StrategyStatusBadge({
  status,
  testId,
}: {
  status: StrategyStatus;
  testId?: string;
}) {
  const { label, tone, title } = PRESENTATION[status];
  const reachable = SUPPORTED_STATUSES.includes(status);

  return (
    <StatusBadge
      tone={reachable ? tone : 'disabled'}
      testId={testId}
      title={
        reachable
          ? title
          : `${title} QuantLab has no execution backend, so no strategy reaches this state.`
      }
    >
      {label}
    </StatusBadge>
  );
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
  runs: readonly { strategy?: { name?: string } | null }[],
): ReadonlySet<string> {
  const names = new Set<string>();
  for (const run of runs) {
    const name = run.strategy?.name;
    if (name) names.add(name);
  }
  return names;
}
