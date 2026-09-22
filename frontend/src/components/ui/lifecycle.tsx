import { StatusBadge } from './status-badge';

/**
 * Where something sits between "measured" and "trading real money".
 *
 * Three states, in increasing order of consequence. `draft` is the fourth and
 * is simply "none of those yet".
 */
export type Lifecycle = 'draft' | 'backtest' | 'paper' | 'live';

export const LIFECYCLE_ORDER: readonly Lifecycle[] = ['backtest', 'paper', 'live'];

/**
 * QuantLab runs backtests. There is no paper-trading engine and no broker, so
 * nothing in this build can honestly be either of the top two.
 *
 * This is the one place on the surface where a decorative choice would be a
 * real hazard. A lit LIVE chip asserts that money is moving; rendering one
 * because it balances the row would be the same class of mistake as flashing a
 * losing position lime. The rest of the app is already careful about this
 * (`SIM` in the nav, `SIMULATED` on invented numbers, `DEMO DATA` beside the
 * dataset) and this follows the same rule: the unreachable states render
 * visibly off, with the reason on hover.
 *
 * Consolidated here because it had been written twice — once inline in
 * `ModelList`, once in the strategy library — with the same reasoning in both
 * docstrings and no shared code. Two copies of a safety-critical label is one
 * copy too many: the day an execution backend arrives, exactly one of them
 * would have been updated.
 */
export const NO_EXECUTION =
  'QuantLab has no execution backend: it measures strategies against stored history and does not trade.';

const PRESENTATION: Record<Lifecycle, { label: string; title: string }> = {
  draft: {
    label: 'Draft',
    title: 'Saved, but never run. Run it to see how it behaved over history.',
  },
  backtest: {
    label: 'Backtest',
    title: 'Measured against stored history. No money, real or notional, has moved.',
  },
  paper: { label: 'Paper', title: 'Trading notional money against a forward feed.' },
  live: { label: 'Live', title: 'Trading real money through a broker.' },
};

/** The states this build can actually reach. */
export const REACHABLE: readonly Lifecycle[] = ['draft', 'backtest'];

export function LifecycleBadge({
  state,
  active = true,
  testId,
}: {
  state: Lifecycle;
  /**
   * Whether this is the state the subject is *in*. False renders the label as
   * an available-but-not-current mode, which is how the model list shows the
   * whole vocabulary at once.
   */
  active?: boolean;
  testId?: string;
}) {
  const { label, title } = PRESENTATION[state];
  const reachable = REACHABLE.includes(state);
  const lit = active && reachable;

  return (
    <StatusBadge
      tone={lit ? (state === 'draft' ? 'idle' : 'active') : 'disabled'}
      testId={testId}
      title={reachable ? title : `${title} ${NO_EXECUTION}`}
    >
      {label}
    </StatusBadge>
  );
}

/**
 * The full vocabulary as one row, with only the reachable state lit.
 *
 * What a terminal usually shows against a model: every mode it could run in,
 * and which one it is in. Here that is always `backtest`, and saying so is
 * more honest than hiding the two modes that do not exist.
 */
export function LifecycleRow({ state = 'backtest' }: { state?: Lifecycle }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {LIFECYCLE_ORDER.map((candidate) => (
        <LifecycleBadge key={candidate} state={candidate} active={candidate === state} />
      ))}
    </span>
  );
}
