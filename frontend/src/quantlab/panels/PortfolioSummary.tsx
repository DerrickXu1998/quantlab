import type { Run, RunPerformance } from '../../api/client';
import { Numeric } from '../chrome/Numeric';
import { StatusBadge } from '../chrome/StatusBadge';

/**
 * The hero. Deliberately the only thing on the surface with room around it —
 * everything else is dense and bordered, so the negative space here is what
 * makes it read as the headline rather than another panel.
 */
export function PortfolioSummary({
  run,
  performance,
}: {
  run: Run;
  performance: RunPerformance;
}) {
  const last = performance.equity[performance.equity.length - 1]?.value ?? null;
  const first = performance.equity[0]?.value ?? null;
  const benchLast = performance.benchmark[performance.benchmark.length - 1]?.value ?? null;
  const benchReturn =
    benchLast !== null && first ? benchLast / first - 1 : null;
  const excess =
    benchReturn !== null ? performance.metrics.total_return - benchReturn : null;

  return (
    <div data-testid="portfolio-summary" className="px-2 py-10 sm:px-8">
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        Book value
      </p>

      <div className="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <Numeric
          value={last}
          format="currency"
          className="font-display text-5xl tracking-[-0.02em]"
        />
        <Numeric
          value={performance.metrics.total_return}
          format="signedPercent"
          tone="signed"
          className="text-xl"
        />
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-2">
          <StatusBadge tone="good">{run.model_name}</StatusBadge>
          <span className="font-mono">v{run.model_version}</span>
        </span>
        <span className="font-mono">
          {run.start_date} → {run.end_date}
        </span>
        <span className="font-mono">
          {run.symbols.length} {run.symbols.length === 1 ? 'instrument' : 'instruments'}
        </span>
        <span className="flex items-center gap-1.5">
          vs benchmark
          <Numeric value={excess} format="signedPercent" tone="signed" />
        </span>
        <StatusBadge tone={run.dataset === 'warehouse' ? 'good' : 'idle'}>
          {run.dataset === 'warehouse' ? 'Live history' : 'Demo data'}
        </StatusBadge>
      </div>
    </div>
  );
}
