import type { PerformanceMetrics } from '../../api/client';
import { Term } from '../../glossary/Term';
import type { TermId } from '../../glossary/terms';
import { StatGrid } from '../../components/ui/layout';
import { Numeric } from '../chrome/Numeric';

function Stat({
  label,
  term,
  children,
  hint,
}: {
  label: string;
  term?: TermId;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1" title={term ? undefined : hint}>
      <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {term ? <Term id={term}>{label}</Term> : label}
      </span>
      <span className="text-lg">{children}</span>
    </div>
  );
}

/**
 * Sharpe, max drawdown and win rate, as the backend computed them.
 *
 * A null is rendered as a dash, not as zero: "not measurable" and "measured,
 * and zero" are different statements about a strategy.
 */
export function StatRow({ metrics }: { metrics: PerformanceMetrics }) {
  return (
    <div data-testid="stat-row">
      <StatGrid>
        <Stat label="Total return" term="total_return">
          <Numeric value={metrics.total_return} format="signedPercent" tone="signed" />
        </Stat>
        <Stat
          label="Sharpe"
          term="sharpe"
          hint="Annualised from daily returns at a zero risk-free rate. A dash means it is not measurable."
        >
          <Numeric value={metrics.sharpe_ratio} format="ratio" />
        </Stat>
        <Stat
          label="Max drawdown"
          term="max_drawdown"
          hint="Worst peak-to-trough fall over the window."
        >
          <Numeric value={metrics.max_drawdown} format="percent" tone="signed" />
        </Stat>
        <Stat
          label="Win rate"
          term="win_rate"
          hint="Share of closed trades that gained. Open positions do not count."
        >
          <Numeric value={metrics.win_rate} format="percent" />
        </Stat>
      </StatGrid>
    </div>
  );
}
