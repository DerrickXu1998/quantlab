import { Inbox } from 'lucide-react';
import { EmptyState } from '../chrome/EmptyState';
import { FlashNumber } from '../chrome/FlashNumber';
import { Numeric } from '../chrome/Numeric';
import type { Position } from '../data/execution';
import { useTick } from '../feed/FeedProvider';

function PositionRow({ position }: { position: Position }) {
  const tick = useTick(position.symbol);
  const live = tick?.price;
  const unrealized = live === undefined ? null : (live - position.avgCost) * position.qty;

  return (
    <tr className="border-t border-border">
      <td className="px-3 py-1.5 font-mono text-[11px]">{position.symbol}</td>
      <td className="px-3 py-1.5 text-right">
        <Numeric value={position.qty} format="integer" className="text-[11px]" />
      </td>
      <td className="px-3 py-1.5 text-right">
        <Numeric value={position.avgCost} className="text-[11px]" />
      </td>
      <td className="px-3 py-1.5 text-right">
        <FlashNumber value={live} format="price" className="text-[11px]" />
      </td>
      <td className="px-3 py-1.5 text-right">
        <FlashNumber value={unrealized} format="signedPrice" tone="signed" className="text-[11px]" />
      </td>
    </tr>
  );
}

/**
 * Positions netted from the session's fills, marked against the simulated
 * feed. Unrealized P&L is the one number here allowed to go red.
 */
export function ExecutionPositions({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <EmptyState
        testId="execution-positions-empty"
        icon={Inbox}
        title="No positions"
        detail="Positions net from the session's fills. Submit an order to open one."
      />
    );
  }

  return (
    <table data-testid="execution-positions" className="w-full">
      <thead>
        <tr className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          <th className="px-3 py-1.5 text-left font-normal">Symbol</th>
          <th className="px-3 py-1.5 text-right font-normal">Qty</th>
          <th className="px-3 py-1.5 text-right font-normal">Avg cost</th>
          <th className="px-3 py-1.5 text-right font-normal">Mark</th>
          <th className="px-3 py-1.5 text-right font-normal" title="Marked against the simulated feed">
            Unrealized
          </th>
        </tr>
      </thead>
      <tbody>
        {positions.map((position) => (
          <PositionRow key={position.symbol} position={position} />
        ))}
      </tbody>
    </table>
  );
}
