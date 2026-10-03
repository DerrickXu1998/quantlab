import type { ExecutionConfig } from '../api/types';
import { DEFAULT_EXECUTION, FILL_TIMING_SHORT } from '../api/types';
import type { PriceAdjustment } from '../api/types';

const ADJUSTMENT_SHORT: Record<PriceAdjustment, string> = {
  split_dividend: 'split + dividend adjusted',
  split: 'split adjusted',
  none: 'raw prices',
};

/**
 * One line of the Advanced summary: a setting as it reads, whether it differs
 * from the default, and whether it deserves a second look even when it does
 * not (zero costs, same-bar fills: defaults that flatter a result).
 */
export interface SummaryItem {
  key: string;
  text: string;
  changed: boolean;
  caution?: string;
}

function pct(fraction: number): string {
  return `${Number((fraction * 100).toFixed(4))}%`;
}

/**
 * What the collapsed execution settings amount to. A changed setting is never
 * hidden behind a closed disclosure: it is listed first, marked, and counted.
 *
 * Holding periods and cooldowns are trading days at every bar size (the
 * engine counts sessions), so they always read in days.
 */
export function executionSummary(execution: ExecutionConfig): SummaryItem[] {
  const unit = 'days';
  const d = DEFAULT_EXECUTION;
  const items: SummaryItem[] = [];
  const push = (key: keyof ExecutionConfig, text: string, caution?: string) =>
    items.push({ key, text, changed: execution[key] !== d[key], caution });

  push(
    'fill_timing',
    FILL_TIMING_SHORT[execution.fill_timing],
    execution.fill_timing === 'signal_close'
      ? 'Fills at the same close the signal was computed from: optimistic unless the order really is market-on-close.'
      : undefined,
  );
  const costs = execution.commission_bps + execution.slippage_bps;
  items.push({
    key: 'costs',
    text: costs === 0 ? 'no costs' : `${execution.commission_bps} + ${execution.slippage_bps} bps costs`,
    changed:
      execution.commission_bps !== d.commission_bps || execution.slippage_bps !== d.slippage_bps,
    caution: costs === 0 ? 'Zero commission and slippage flatter every trade.' : undefined,
  });
  if (execution.max_positions !== null) push('max_positions', `max ${execution.max_positions} positions`);
  if (execution.max_position_pct !== d.max_position_pct) {
    push('max_position_pct', `max ${pct(execution.max_position_pct)} a position`);
  }
  if (execution.stop_loss_pct !== null) push('stop_loss_pct', `stop ${pct(execution.stop_loss_pct)}`);
  if (execution.take_profit_pct !== null) {
    push('take_profit_pct', `target ${pct(execution.take_profit_pct)}`);
  }
  if (execution.trailing_stop_pct !== null) {
    push('trailing_stop_pct', `trailing ${pct(execution.trailing_stop_pct)}`);
  }
  if (execution.atr_stop_multiple !== null) {
    push('atr_stop_multiple', `ATR stop ×${execution.atr_stop_multiple}`);
  }
  if (execution.max_holding_days !== null) {
    push('max_holding_days', `hold ≤ ${execution.max_holding_days} ${unit}`);
  }
  if (execution.min_holding_days !== d.min_holding_days) {
    push('min_holding_days', `hold ≥ ${execution.min_holding_days} ${unit}`);
  }
  if (execution.cooldown_days !== d.cooldown_days) {
    push('cooldown_days', `cooldown ${execution.cooldown_days} ${unit}`);
  }
  if (execution.allow_shorts) push('allow_shorts', 'shorts allowed');
  push(
    'price_adjustment',
    ADJUSTMENT_SHORT[execution.price_adjustment],
    execution.price_adjustment === 'none'
      ? 'Raw prices: a split inside the window reads as a crash or a spike.'
      : undefined,
  );
  if (execution.intraday_resolution !== d.intraday_resolution) {
    push('intraday_resolution', `${execution.intraday_resolution} accuracy`);
  }
  // Changed first: what the reader did is what they most need to see.
  return [...items.filter((item) => item.changed), ...items.filter((item) => !item.changed)];
}
