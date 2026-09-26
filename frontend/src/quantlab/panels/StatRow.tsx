import type { PerformanceMetrics } from '../../api/client';
import { StatGrid } from '../../components/ui/layout';
import { Numeric } from '../chrome/Numeric';

function Stat({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1" title={hint}>
      <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
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
        <Stat label="Total return">
          <Numeric value={metrics.total_return} format="signedPercent" tone="signed" />
        </Stat>
        <Stat
          label="Sharpe"
          hint="Annualised from daily returns at a zero risk-free rate. A dash means it is not measurable."
        >
          <Numeric value={metrics.sharpe_ratio} format="ratio" />
        </Stat>
        <Stat label="Max drawdown" hint="Worst peak-to-trough fall over the window.">
          <Numeric value={metrics.max_drawdown} format="percent" tone="signed" />
        </Stat>
        <Stat
          label="Win rate"
          hint="Share of closed trades that gained. Open positions do not count."
        >
          <Numeric value={metrics.win_rate} format="percent" />
        </Stat>
      </StatGrid>
    </div>
  );
}
