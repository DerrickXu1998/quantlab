import { ChartCandlestick } from 'lucide-react';
import type { PriceBar } from '../../api/client';
import { CandlestickChart } from '../../components/CandlestickChart';
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
            <CandlestickChart bars={bars} autoSize />
          </div>
          <p className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            {formatCount(bars.length)} bars · {bars[0].date} → {last?.date}
          </p>
        </div>
      )}
    </Panel>
  );
}
