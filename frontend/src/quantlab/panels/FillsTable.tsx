import { ReceiptText } from 'lucide-react';
import { EmptyState } from '../chrome/EmptyState';
import { Numeric } from '../chrome/Numeric';
import { StatusBadge } from '../chrome/StatusBadge';
import type { Fill } from '../data/execution';

/**
 * The session's simulated fills, newest first. Filled in full at the quoted
 * price — there is no partial fill, because there is no matching engine.
 *
 * Scrolling belongs to the panel around this, not to a second scroller in
 * here: nested, the two edges compete and the sticky header sticks to the
 * wrong box. The empty state is deliberately compact — the band it sits in is
 * capped, and the order book above it wants every pixel absence does not need.
 */
export function FillsTable({ fills }: { fills: Fill[] }) {
  if (fills.length === 0) {
    return (
      <EmptyState
        testId="fills-empty"
        icon={ReceiptText}
        title="No fills yet"
        detail="Orders fill immediately at the simulated price."
        className="py-6"
      />
    );
  }

  return (
    <table data-testid="fills-table" className="w-full">
      <thead className="sticky top-0 z-10 bg-card">
        <tr className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          <th className="px-3 py-1.5 text-left font-normal">Time</th>
          <th className="px-3 py-1.5 text-left font-normal">Symbol</th>
          <th className="px-3 py-1.5 text-left font-normal">Side</th>
          <th className="px-3 py-1.5 text-right font-normal">Qty</th>
          <th className="px-3 py-1.5 text-right font-normal">Price</th>
        </tr>
      </thead>
      <tbody>
        {[...fills].reverse().map((fill) => (
          <tr key={fill.id} className="border-t border-border">
            <td className="px-3 py-1.5 font-mono text-[11px] text-muted-foreground">{fill.time}</td>
            <td className="px-3 py-1.5 font-mono text-[11px]">{fill.symbol}</td>
            <td className="px-3 py-1.5">
              <StatusBadge tone={fill.side === 'BUY' ? 'active' : 'idle'}>{fill.side}</StatusBadge>
            </td>
            <td className="px-3 py-1.5 text-right">
              <Numeric value={fill.qty} format="integer" className="text-[11px]" />
            </td>
            <td className="px-3 py-1.5 text-right">
              <Numeric value={fill.price} className="text-[11px]" />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
