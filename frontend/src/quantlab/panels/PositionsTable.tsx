import { Inbox } from 'lucide-react';
import type { Trade } from '../../api/client';
import { EmptyState } from '../chrome/EmptyState';
import { Numeric } from '../chrome/Numeric';
import { displaySymbol } from '../../research/format';

function PositionRow({ trade }: { trade: Trade }) {
  return (
    <tr className="border-t border-border">
      <td className="px-3 py-1.5 type-data">{displaySymbol(trade.symbol)}</td>
      <td className="px-3 py-1.5 type-data text-muted-foreground">{trade.entry_date}</td>
      <td className="px-3 py-1.5 text-right">
        <Numeric value={trade.entry_price} className="text-xs" />
      </td>
      <td className="px-3 py-1.5 text-right">
        <Numeric value={trade.exit_price} className="text-xs" />
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
}

/**
 * Positions still open at the end of the run's window.
 *
 * Entry, mark and return are the backend's figures; nothing here is
 * recomputed in the browser.
 */
export function PositionsTable({ trades }: { trades: Trade[] }) {
  const open = trades.filter((trade) => trade.open);

  if (open.length === 0) {
    return (
      <EmptyState
        testId="positions-empty"
        icon={Inbox}
        title="No open positions"
        detail="Every position the run opened was closed inside the window."
      />
    );
  }

  return (
    <table data-testid="positions-table" className="w-full">
      <thead>
        <tr className="type-label text-muted-foreground">
          <th className="px-3 py-1.5 text-left font-normal">Symbol</th>
          <th className="px-3 py-1.5 text-left font-normal">Entry</th>
          <th className="px-3 py-1.5 text-right font-normal">Price</th>
          <th className="px-3 py-1.5 text-right font-normal">Mark</th>
          <th className="px-3 py-1.5 text-right font-normal">Return</th>
        </tr>
      </thead>
      <tbody>
        {open.map((trade) => (
          <PositionRow key={`${trade.symbol}-${trade.entry_date}`} trade={trade} />
        ))}
      </tbody>
    </table>
  );
}
