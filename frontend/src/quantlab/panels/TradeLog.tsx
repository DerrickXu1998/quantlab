import { FileSearch } from 'lucide-react';
import type { Trade } from '../../api/client';
import { EmptyState } from '../chrome/EmptyState';
import { Numeric } from '../chrome/Numeric';
import { StatusBadge } from '../chrome/StatusBadge';

/**
 * Every position the run took, closed and open.
 *
 * Paired from the run's own signals against its own bars, in the backend. An
 * open row is marked to the last close and says so, so it cannot be read as a
 * realised result.
 */
export function TradeLog({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return (
      <EmptyState
        testId="trade-log-empty"
        icon={FileSearch}
        title="No trades"
        detail="The run produced no signal pairs to open a position with. That is a result, not a failure."
      />
    );
  }

  return (
    <div className="max-h-72 overflow-y-auto">
      <table data-testid="trade-log" className="w-full">
        <thead className="sticky top-0 bg-card">
          <tr className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="px-3 py-1.5 text-left font-normal">Symbol</th>
            <th className="px-3 py-1.5 text-left font-normal">In</th>
            <th className="px-3 py-1.5 text-left font-normal">Out</th>
            <th className="px-3 py-1.5 text-right font-normal">Entry</th>
            <th className="px-3 py-1.5 text-right font-normal">Exit</th>
            <th className="px-3 py-1.5 text-right font-normal">Return</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={`${trade.symbol}-${trade.entry_date}`} className="border-t border-border">
              <td className="px-3 py-1.5 font-mono text-[11px]">{trade.symbol}</td>
              <td className="px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
                {trade.entry_date}
              </td>
              <td className="px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
                {trade.exit_date ?? <StatusBadge tone="active">Open</StatusBadge>}
              </td>
              <td className="px-3 py-1.5 text-right">
                <Numeric value={trade.entry_price} className="text-[11px]" />
              </td>
              <td className="px-3 py-1.5 text-right">
                <Numeric value={trade.exit_price} className="text-[11px]" />
              </td>
              <td className="px-3 py-1.5 text-right">
                <Numeric
                  value={trade.return_pct}
                  format="signedPercent"
                  tone="signed"
                  className="text-[11px]"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
