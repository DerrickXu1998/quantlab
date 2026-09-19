import { Inbox } from 'lucide-react';
import type { Trade } from '../../api/client';
import { EmptyState } from '../chrome/EmptyState';
import { FlashNumber } from '../chrome/FlashNumber';
import { Numeric } from '../chrome/Numeric';
import { useTick } from '../feed/FeedProvider';

function PositionRow({ trade }: { trade: Trade }) {
  const tick = useTick(trade.symbol);
  // Marked at the run's last close by the backend; the live column re-marks it
  // against the simulated feed, which is why that column alone is tagged.
  const live = tick?.price;
  const liveReturn = live ? live / trade.entry_price - 1 : null;

  return (
    <tr className="border-t border-border">
      <td className="px-3 py-1.5 font-mono text-[11px]">{trade.symbol}</td>
      <td className="px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
        {trade.entry_date}
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
      <td className="px-3 py-1.5 text-right">
        <FlashNumber
          value={liveReturn}
          format="signedPercent"
          tone="signed"
          className="text-[11px]"
        />
      </td>
    </tr>
  );
}

/**
 * Positions still open at the end of the run's window.
 *
 * Entry, mark and return are the backend's figures. The final column re-marks
 * them against the simulated feed and is the only invented number here.
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
        <tr className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          <th className="px-3 py-1.5 text-left font-normal">Symbol</th>
          <th className="px-3 py-1.5 text-left font-normal">Entry</th>
          <th className="px-3 py-1.5 text-right font-normal">Price</th>
          <th className="px-3 py-1.5 text-right font-normal">Mark</th>
          <th className="px-3 py-1.5 text-right font-normal">Return</th>
          <th className="px-3 py-1.5 text-right font-normal" title="Re-marked against the simulated feed">
            Live
          </th>
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
