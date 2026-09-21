import { Activity, ListOrdered, ServerCrash } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { Instrument } from '../../api/client';
import { Button } from '../../components/ui/button';
import { CascadeItem } from '../chrome/Cascade';
import { EmptyState } from '../chrome/EmptyState';
import { FlashNumber } from '../chrome/FlashNumber';
import { Panel } from '../chrome/Panel';
import { derivePositions, type Fill } from '../data/execution';
import { buildOrderBook } from '../data/orderBook';
import { useTick } from '../feed/FeedProvider';
import { ExecutionPositions } from '../panels/ExecutionPositions';
import { FillsTable } from '../panels/FillsTable';
import { OrderBook } from '../panels/OrderBook';
import { OrderTicket, type OrderRequest } from '../panels/OrderTicket';

const SIM_BOOK =
  'There is no execution backend; the book is generated around the simulated feed price and reshuffles on every tick.';
const SIM_FILLS = 'Orders fill in full and immediately at the simulated price — there is no matching engine.';
const SIM_POSITIONS = 'Netted from the session’s simulated fills and marked against the simulated feed.';

export function ExecutionView({
  instruments,
  feedError,
  onFeedRetry,
}: {
  instruments: Instrument[];
  feedError: string | null;
  /** Offered on the feed-error state; absent in contexts that cannot retry. */
  onFeedRetry?: () => void;
}) {
  const [symbol, setSymbol] = useState<string | null>(null);
  const [fills, setFills] = useState<Fill[]>([]);
  const nextId = useRef(1);

  useEffect(() => {
    if (symbol === null && instruments.length > 0) setSymbol(instruments[0].symbol);
  }, [instruments, symbol]);

  const tick = useTick(symbol ?? '');
  const book = useMemo(() => (tick ? buildOrderBook(tick.price) : null), [tick]);
  const positions = useMemo(() => derivePositions(fills), [fills]);

  const submit = (order: OrderRequest) => {
    const fill: Fill = {
      ...order,
      id: nextId.current,
      time: new Date().toISOString().slice(11, 19),
    };
    nextId.current += 1;
    setFills((current) => [...current, fill].slice(-50));
  };

  if (feedError) {
    return (
      <EmptyState
        testId="execution-feed-error"
        icon={ServerCrash}
        tone="error"
        title="Feed disconnected"
        detail={feedError}
        action={
          onFeedRetry ? (
            <Button type="button" variant="outline" size="sm" onClick={onFeedRetry}>
              Retry
            </Button>
          ) : undefined
        }
      />
    );
  }

  if (instruments.length === 0) {
    return (
      <EmptyState
        testId="execution-empty"
        icon={ListOrdered}
        title="No instruments"
        detail="The watchlist is empty, so there is nothing to trade."
      />
    );
  }

  return (
    // Order flow reads left to right: the book, then the ticket. Fills and
    // positions close the loop along the bottom.
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-px overflow-y-auto bg-border lg:grid-cols-[minmax(0,1fr)_320px] lg:grid-rows-[minmax(0,1fr)_auto]">
      <CascadeItem index={0} className="min-w-0 bg-background p-4">
        <Panel
          title={symbol ? `${symbol} — order book` : 'Order book'}
          className="flex h-full flex-col border-0"
          bodyClassName="min-h-0 flex-1 p-0"
          simulated={SIM_BOOK}
          actions={
            <FlashNumber
              value={tick?.price}
              format="price"
              tone="accent"
              className="text-[11px]"
            />
          }
        >
          {book ? (
            <OrderBook book={book} />
          ) : (
            <EmptyState icon={Activity} title="Waiting for the feed…" role="status" />
          )}
        </Panel>
      </CascadeItem>

      <CascadeItem index={1} className="bg-background p-4">
        <Panel title="Order ticket" className="border-0" simulated={SIM_FILLS}>
          <OrderTicket
            instruments={instruments}
            symbol={symbol}
            onSymbolChange={setSymbol}
            onSubmit={submit}
          />
        </Panel>
      </CascadeItem>

      <CascadeItem index={2} className="min-w-0 bg-background">
        <Panel title="Recent fills" className="border-0" bodyClassName="p-0" simulated={SIM_FILLS}>
          <FillsTable fills={fills} />
        </Panel>
      </CascadeItem>

      <CascadeItem index={3} className="min-w-0 bg-background">
        <Panel title="Positions" className="border-0" bodyClassName="p-0" simulated={SIM_POSITIONS}>
          <ExecutionPositions positions={positions} />
        </Panel>
      </CascadeItem>
    </div>
  );
}
