import type { BenchmarkRegression } from '../../api/types';
import { StatGrid } from '../../components/ui/layout';
import { Numeric } from '../chrome/Numeric';
import { Panel } from '../chrome/Panel';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

/** Below this many paired days the backend returns no regression at all. */
const MIN_OBSERVATIONS = 60;

function Stat({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1" title={hint}>
      <span className={MICRO}>{label}</span>
      <span className="text-lg">{children}</span>
    </div>
  );
}

/**
 * The sentence a reader actually wants: how much of this is the market?
 *
 * Wording only -- every number in it is one the backend sent. Buckets are the
 * conventional reading of R², not a new statistic.
 */
function reading(fit: BenchmarkRegression): string {
  const exposure =
    fit.beta < 0
      ? `moves against buy-and-hold of the same names (beta ${fit.beta.toFixed(2)})`
      : `moves about ${Math.round(fit.beta * 100)}% as much as buy-and-hold of the same names`;
  const explained =
    fit.r_squared >= 0.7
      ? 'most of its day-to-day movement is that exposure'
      : fit.r_squared >= 0.3
        ? 'part of its movement is that exposure, part is its own timing'
        : 'little of its movement is explained by simply holding the names';
  return `The strategy ${exposure}; ${explained}.`;
}

/**
 * Alpha, beta and R² against the run's own benchmark (book L08, gap F5/U3).
 *
 * The benchmark is the equal-weight buy-and-hold of the selection, not an
 * index -- the store has no index series yet (gap D1) -- so this measures what
 * the strategy's timing added over holding the same names, which is the
 * question a strategy backtest should answer first.
 */
export function BenchmarkPanel({
  regression,
}: {
  regression: BenchmarkRegression | null | undefined;
}) {
  // An older backend sends no field at all: render nothing rather than an
  // empty panel claiming the regression was attempted.
  if (regression === undefined) return null;

  return (
    <div data-testid="benchmark-panel">
      <Panel title="Against buy & hold" bodyClassName="space-y-3">
        {regression === null ? (
          <p data-testid="benchmark-unmeasured" className="text-xs text-muted-foreground">
            Not measurable: a regression needs at least {MIN_OBSERVATIONS} overlapping trading days
            and a benchmark that moved. A dash would be more honest than a beta of 0, which would
            read as market-neutral.
          </p>
        ) : (
          <>
            <StatGrid min="7.5rem">
              <Stat
                label="Alpha (ann.)"
                hint="Annualised intercept of daily strategy returns on daily benchmark returns, risk-free rate taken as zero."
              >
                <Numeric value={regression.alpha} format="signedPercent" tone="signed" />
              </Stat>
              <Stat
                label="Beta"
                hint="Sensitivity to the benchmark: 1 moves with it, 0 is unrelated, negative moves against it."
              >
                <Numeric value={regression.beta} format="ratio" />
              </Stat>
              <Stat
                label="R²"
                hint="Share of the strategy's daily variance explained by the benchmark."
              >
                <Numeric value={regression.r_squared} format="ratio" />
              </Stat>
              <Stat
                label="Tracking error"
                hint="Annualised volatility of strategy minus benchmark returns."
              >
                <Numeric value={regression.tracking_error ?? null} format="percent" />
              </Stat>
              <Stat
                label="Info ratio"
                hint="Annualised active return over tracking error. A dash means it is not measurable."
              >
                <Numeric value={regression.information_ratio ?? null} format="ratio" />
              </Stat>
              <Stat label="Days" hint="Paired daily returns the regression used.">
                <Numeric value={regression.observations} format="integer" />
              </Stat>
            </StatGrid>
            <p data-testid="benchmark-reading" className="text-xs text-muted-foreground">
              {reading(regression)} Benchmark: equal-weight buy-and-hold of this run's names, not an
              index; risk-free rate taken as zero.
            </p>
          </>
        )}
      </Panel>
    </div>
  );
}
