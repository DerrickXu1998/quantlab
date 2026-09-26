import { FileSearch } from 'lucide-react';
import type { ExitReason, TradeV2 } from '../../api/types';
import { EXIT_REASON_LABELS } from '../../api/types';
import { EmptyState } from '../chrome/EmptyState';
import { Numeric } from '../chrome/Numeric';
import { StatusBadge } from '../chrome/StatusBadge';

/** A reason the engine did not report is a dash, never a guess. */
function exitReasonLabel(reason: ExitReason | null | undefined): string | null {
  if (reason === null || reason === undefined) return null;
  return EXIT_REASON_LABELS[reason] ?? reason;
}

/**
 * Every position the run took, closed and open.
 *
 * Paired from the run's own signals against its own bars, in the backend. An
 * open row is marked to the last close and says so, so it cannot be read as a
 * realised result.
 *
 * Side, quantity, exit reason, P&L and fees arrived with the execution
 * criteria (§5) and are what make a row auditable: "why did this close?" and
 * "what did it cost?" are the first two questions anyone asks of a trade, and
 * before this they were unanswerable from the log. Every one of them is
 * optional on the wire — a run recorded before the change simply shows a dash
 * rather than a fabricated value.
 */
export function TradeLog({ trades }: { trades: TradeV2[] }) {
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

  const head = 'px-3 py-1.5 text-left font-normal';
  const headRight = 'px-3 py-1.5 text-right font-normal';

  return (
    <div className="max-h-72 overflow-y-auto">
      <table data-testid="trade-log" className="w-full">
        <thead className="sticky top-0 bg-card">
          <tr className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            <th className={head}>Symbol</th>
            <th className={head}>Side</th>
            <th className={head}>In</th>
            <th className={head}>Out</th>
            <th className={headRight}>Qty</th>
            <th className={headRight}>Entry</th>
            <th className={headRight}>Exit</th>
            <th className={head}>Why</th>
            <th className={headRight}>P&amp;L</th>
            <th className={headRight}>Fees</th>
            <th className={headRight}>Return</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, index) => {
            const reason = exitReasonLabel(trade.exit_reason);
            return (
              <tr
                key={`${trade.symbol}-${trade.entry_date}-${index}`}
                className="border-t border-border"
              >
                <td className="px-3 py-1.5 font-mono text-[11px]">{trade.symbol}</td>
                <td className="px-3 py-1.5 font-mono text-[11px] uppercase text-muted-foreground">
                  {trade.side ?? '—'}
                </td>
                <td className="px-3 py-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                  {trade.entry_date}
                </td>
                <td className="px-3 py-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                  {trade.exit_date ?? <StatusBadge tone="active">Open</StatusBadge>}
                </td>
                <td className="px-3 py-1.5 text-right">
                  <Numeric value={trade.qty} format="ratio" className="text-xs" />
                </td>
                <td className="px-3 py-1.5 text-right">
                  <Numeric value={trade.entry_price} className="text-xs" />
                </td>
                <td className="px-3 py-1.5 text-right">
                  <Numeric value={trade.exit_price} className="text-xs" />
                </td>
                <td className="px-3 py-1.5 text-xs text-muted-foreground">
                  {trade.open ? (
                    <span title="Still held at the end of the window.">still open</span>
                  ) : (
                    (reason ?? '—')
                  )}
                </td>
                <td className="px-3 py-1.5 text-right">
                  <Numeric
                    value={trade.pnl}
                    format="signedPrice"
                    tone="signed"
                    className="text-xs"
                  />
                </td>
                <td className="px-3 py-1.5 text-right">
                  <Numeric
                    value={trade.fees}
                    format="price"
                    tone="muted"
                    className="text-xs"
                  />
                </td>
                <td className="px-3 py-1.5 text-right">
                  <Numeric
                    value={trade.return_pct}
                    format="signedPercent"
                    tone="signed"
                    className="text-xs"
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
