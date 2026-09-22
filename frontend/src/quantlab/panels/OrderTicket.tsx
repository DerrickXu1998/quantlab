import { useState } from 'react';
import type { Instrument } from '../../api/client';
import { Button } from '../../components/ui/button';
import { fieldClasses } from '../../components/ui/field';
import { Numeric } from '../chrome/Numeric';
import type { Side } from '../data/execution';
import { useTick } from '../feed/FeedProvider';

export interface OrderRequest {
  symbol: string;
  side: Side;
  qty: number;
  type: 'market' | 'limit';
  price: number;
}

const INPUT = fieldClasses;

function Toggle<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly T[];
  value: T;
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="grid grid-cols-2 gap-px rounded-sm border border-border bg-border">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={value === option}
          onClick={() => onChange(option)}
          // BUY/SELL and market/limit are the two choices on this screen a
          // mis-tap actually costs something for, so they get the full 44px on
          // touch even though the ticket is compact everywhere else.
          className={`h-11 px-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors lg:h-auto lg:py-1.5 ${
            value === option
              ? option === 'SELL'
                ? // SELL is a side, not a loss — muted, not red.
                  'bg-muted-foreground/10 text-foreground'
                : 'bg-primary/10 text-primary'
              : 'bg-card text-muted-foreground hover:text-foreground'
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

/**
 * The order ticket. Market orders fill at the current simulated price, limits
 * at the named price, both in full and immediately — there is no matching
 * engine, and the panel carrying the fills says so.
 */
export function OrderTicket({
  instruments,
  symbol,
  onSymbolChange,
  onSubmit,
}: {
  instruments: Instrument[];
  symbol: string | null;
  onSymbolChange: (symbol: string) => void;
  onSubmit: (order: OrderRequest) => void;
}) {
  const [side, setSide] = useState<Side>('BUY');
  const [qty, setQty] = useState('10');
  const [type, setType] = useState<'market' | 'limit'>('market');
  const [limitPrice, setLimitPrice] = useState('');
  const tick = useTick(symbol ?? '');

  const qtyValue = Number.parseInt(qty, 10);
  const limitValue = Number.parseFloat(limitPrice);
  const fillPrice = type === 'market' ? tick?.price : limitValue;
  const valid =
    symbol !== null &&
    Number.isFinite(qtyValue) &&
    qtyValue > 0 &&
    fillPrice !== undefined &&
    Number.isFinite(fillPrice) &&
    fillPrice > 0;

  return (
    <form
      data-testid="order-ticket"
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || symbol === null || fillPrice === undefined) return;
        onSubmit({ symbol, side, qty: qtyValue, type, price: fillPrice });
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          Symbol
        </span>
        <select
          value={symbol ?? ''}
          onChange={(event) => onSymbolChange(event.target.value)}
          className={INPUT}
        >
          {instruments.map((instrument) => (
            <option key={instrument.symbol} value={instrument.symbol}>
              {instrument.symbol}
            </option>
          ))}
        </select>
      </label>

      <Toggle
        label="Side"
        options={['BUY', 'SELL'] as Side[]}
        value={side}
        onChange={setSide}
      />

      <label className="flex flex-col gap-1">
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          Quantity
        </span>
        <input
          type="number"
          min={1}
          step={1}
          value={qty}
          onChange={(event) => setQty(event.target.value)}
          className={INPUT}
        />
      </label>

      <Toggle
        label="Order type"
        options={['market', 'limit'] as const}
        value={type}
        onChange={(next) => {
          setType(next);
          if (next === 'limit' && limitPrice === '' && tick) {
            setLimitPrice(tick.price.toFixed(2));
          }
        }}
      />

      {type === 'limit' ? (
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            Limit price
          </span>
          <input
            type="number"
            min={0}
            step="0.01"
            value={limitPrice}
            onChange={(event) => setLimitPrice(event.target.value)}
            className={INPUT}
          />
        </label>
      ) : null}

      <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        <span>{type === 'market' ? 'Est. fill' : 'Fill price'}</span>
        <Numeric value={fillPrice} className="text-[11px] text-foreground" />
      </div>

      <Button type="submit" disabled={!valid} className="py-2">
        Submit order
      </Button>
    </form>
  );
}
