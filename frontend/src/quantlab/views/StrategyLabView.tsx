import { useMemo } from 'react';
import { useRoute } from '../../chrome/router';
import { StrategyBuilder, type StrategySeed } from '../../strategies/StrategyBuilder';
import type { Instrument } from '../../api/client';
import { useInstruments } from '../../research/company/useCompany';

/**
 * Strategies: combine several signals into one set of trading rules, point it
 * at a universe of tickers, and backtest the trades.
 *
 * It used to carry two more tabs -- a single-rule "Signal lab" and a
 * "Point-in-time" filings inspector -- which were Research's Test and Company
 * views again under other names, and made it impossible to tell the two
 * destinations apart. One ticker is Research; many tickers under one set of
 * rules is here.
 *
 * A signal row still hands over a rule (`?model=` with `p_<name>` values, and
 * the `symbol` it fired on): it arrives as the builder's first entry signal,
 * with that ticker as the universe, instead of in a separate single-rule form.
 */
export function StrategyLabView({ instruments }: { instruments: Instrument[] }) {
  const route = useRoute();
  // The whole catalogue, not the shell's eight-name watchlist it is handed:
  // a universe drawn from the first eight tickers is not a universe, and that
  // is all the old picker ever offered. The watchlist stands in until the
  // catalogue arrives.
  const catalogue = useInstruments();
  const universe = catalogue.data.length > 0 ? catalogue.data : instruments;
  const query = route.params.toString();

  const seed = useMemo<StrategySeed | null>(() => {
    const params = new URLSearchParams(query);
    const model = params.get('model');
    if (!model) return null;
    const values: Record<string, string> = {};
    for (const [key, value] of params) {
      if (key.startsWith('p_')) values[key.slice(2)] = value;
    }
    const symbol = params.get('symbol');
    return { key: query, model, values, symbols: symbol ? [symbol] : [] };
  }, [query]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <p className="shrink-0 border-b border-border px-4 py-2.5 text-sm text-muted-foreground">
        <span className="font-mono text-xs uppercase tracking-[0.12em] text-foreground">
          Strategies
        </span>{' '}
        — combine several signals into one set of trading rules, choose a universe of tickers, and
        backtest the trades it would have made. To study a single ticker, use Research.
      </p>
      <StrategyBuilder instruments={universe} seed={seed} />
    </div>
  );
}
