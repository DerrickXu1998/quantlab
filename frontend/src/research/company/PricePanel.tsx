import { ChartCandlestick } from 'lucide-react';
import type { PriceBar } from '../../api/client';
import {
  CandlestickChart,
  type ChartLine,
  type ChartSignal,
} from '../../components/CandlestickChart';
import { cn } from '../../lib/utils';
import { formatCount, formatPrice } from '../format';
import { Panel, PanelEmpty, PanelState } from './Panel';
import type { ReadStatus } from './useCompany';

export interface PricePanelProps {
  symbol: string;
  asOf: string;
  bars: PriceBar[];
  status: ReadStatus;
  message: string | null;
  currency: string | null;
  onRetry: () => void;
  /** Signals from the models applied in the Models panel. */
  signals?: ChartSignal[];
  /** Lines the applied models compared, e.g. sma-crossover's two averages. */
  lines?: ChartLine[];
}

/**
 * The price history, cut at the as-of date.
 *
 * The chart is `components/CandlestickChart` unchanged — it already reads the
 * live design tokens off its own container and handles theme, hover and
 * resize. What is different here is the *series it is given*: bars up to the
 * as-of date and no further, so the chart and the accounts beside it are
 * answering the same question. A chart running to today next to accounts frozen
 * in 2019 is two different dates on one screen, which is exactly the confusion
 * the point-in-time work exists to remove.
 */
export function PricePanel({
  symbol,
  asOf,
  bars,
  status,
  message,
  currency,
  onRetry,
  signals,
  lines,
}: PricePanelProps) {
  const last = bars.length > 0 ? bars[bars.length - 1] : null;

  return (
    <Panel
      icon={ChartCandlestick}
      title="Price"
      purpose="Daily bars up to the as-of date and no further, so the chart is cut where the accounts are."
      testId="company-price"
      fill
      aside={
        last ? (
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            {formatPrice(last.close, currency ?? undefined)}
          </span>
        ) : null
      }
    >
      {status !== 'ready' ? (
        <PanelState
          status={status}
          message={message}
          subject="the price history"
          route="GET /instruments/{symbol}/prices"
          onRetry={onRetry}
          testId="company-price-state"
        />
      ) : bars.length === 0 ? (
        <PanelEmpty
          title="No bars on or before this date"
          detail={`${symbol} has no price history up to ${asOf}. Move the as-of date forward, or this name began trading later.`}
          testId="company-price-empty"
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
          <div className="min-h-[320px] flex-1">
            <CandlestickChart bars={bars} signals={signals} lines={lines} autoSize />
          </div>
          <p className="shrink-0 font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground">
            {formatCount(bars.length)} bars · {bars[0].date} → {last?.date}
            {signals && signals.length > 0 ? (
              <>
                {' · '}
                <span className="text-primary">▲ bullish</span>{' '}
                <span className="text-destructive">▼ bearish</span> ·{' '}
                {formatCount(signals.length)} model signals
              </>
            ) : null}
          </p>
          {lines && lines.length > 0 ? (
            <ul
              aria-label="Model lines"
              className="flex shrink-0 flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground"
            >
              {lines.map((line) => (
                <li key={line.key} className="flex items-center gap-1.5">
                  <LineSwatch line={line} />
                  {line.label}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </Panel>
  );
}

/** A short stroke in the line's own colour, weight and dash. */
function LineSwatch({ line }: { line: ChartLine }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block w-5',
        line.look.tone === 'foreground' ? 'border-foreground' : 'border-muted-foreground',
        line.look.width === 1 ? 'border-t' : 'border-t-2',
        line.look.style === 'dashed' && 'border-dashed',
        line.look.style === 'dotted' && 'border-dotted',
      )}
    />
  );
}
