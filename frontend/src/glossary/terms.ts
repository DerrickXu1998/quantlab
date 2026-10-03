import type { UnitKind } from './units';

/**
 * QuantLab's technical vocabulary, in one place.
 *
 * Every hover explanation on the site reads from here, so a term is defined
 * once and says the same thing on every screen. To add a term: add an entry,
 * then wrap the label where it appears in <Term id="...">. To change wording:
 * change it here, nowhere else. The Glossary (header, book icon) lists all of
 * them.
 *
 * `short` is one or two plain sentences: what it is and why it matters to a
 * backtest. No formulas unless the formula is the clearest way to say it.
 */
export interface TermDefinition {
  label: string;
  short: string;
  unit?: UnitKind;
  /** Where the term belongs, for grouping in the Glossary. */
  group: TermGroup;
}

export type TermGroup = 'Results' | 'Benchmark' | 'Execution' | 'Strategy' | 'Data';

export const TERMS = {
  // --- Results ---------------------------------------------------------------
  total_return: {
    label: 'Total return',
    short: 'How much the book grew or shrank over the whole window, after costs.',
    unit: 'percent',
    group: 'Results',
  },
  sharpe: {
    label: 'Sharpe ratio',
    short:
      'Average return divided by its volatility, annualised, at a zero risk-free rate. Above 1 is good for a backtest; a dash means it cannot be measured (too few returns, or none varied).',
    unit: 'annualised-ratio',
    group: 'Results',
  },
  max_drawdown: {
    label: 'Max drawdown',
    short:
      'The worst fall from a peak in equity to the low that followed it. How much pain the strategy put you through.',
    unit: 'percent',
    group: 'Results',
  },
  win_rate: {
    label: 'Win rate',
    short:
      'Share of closed trades that made money. High win rates can still lose if the losers are large.',
    unit: 'percent',
    group: 'Results',
  },
  trades: {
    label: 'Trades',
    short:
      'Round trips closed in the window: one entry and its exit. Few trades means the other figures rest on little evidence.',
    unit: 'count',
    group: 'Results',
  },
  equity_curve: {
    label: 'Equity curve',
    short: 'The value of the book over time, cash plus positions marked at each session close.',
    unit: 'currency',
    group: 'Results',
  },

  // --- Benchmark -------------------------------------------------------------
  benchmark: {
    label: 'Benchmark (buy & hold)',
    short:
      'Equal-weight buy-and-hold of the same tickers over the same window: what simply owning them would have done. The bar a strategy has to clear.',
    unit: 'percent',
    group: 'Benchmark',
  },
  excess_return: {
    label: 'vs buy & hold',
    short:
      "The strategy's total return minus the benchmark's. Positive means the rules added something over just holding.",
    unit: 'percent',
    group: 'Benchmark',
  },
  alpha: {
    label: 'Alpha',
    short:
      'Return the strategy earned that the benchmark does not explain, annualised. The part attributable to the rules.',
    unit: 'percent',
    group: 'Benchmark',
  },
  beta: {
    label: 'Beta',
    short:
      'How much the strategy moves with the benchmark: 1 moves one-for-one, 0 is unrelated, below 0 moves against it.',
    unit: 'ratio',
    group: 'Benchmark',
  },
  r_squared: {
    label: 'R²',
    short:
      "Share of the strategy's day-to-day moves the benchmark explains: near 1 means it is mostly the market.",
    unit: 'ratio',
    group: 'Benchmark',
  },
  tracking_error: {
    label: 'Tracking error',
    short:
      'Volatility of the difference between the strategy and the benchmark, annualised: how far it strays from simply holding.',
    unit: 'percent',
    group: 'Benchmark',
  },
  information_ratio: {
    label: 'Information ratio',
    short:
      'Excess return over the benchmark divided by tracking error: Sharpe, measured against holding instead of cash.',
    unit: 'annualised-ratio',
    group: 'Benchmark',
  },

  // --- Execution -------------------------------------------------------------
  initial_capital: {
    label: 'Initial capital',
    short: 'The notional book the run starts with. Every result is measured against it.',
    unit: 'currency',
    group: 'Execution',
  },
  position_sizing: {
    label: 'Position sizing',
    short:
      'How much of the book each new position gets: an equal share, a fixed fraction, fixed cash, or a volatility target.',
    unit: 'choice',
    group: 'Execution',
  },
  max_positions: {
    label: 'Max positions',
    short: 'The most positions open at once. Further entry signals are refused until one closes.',
    unit: 'count',
    group: 'Execution',
  },
  max_position_pct: {
    label: 'Max position size',
    short: 'The largest share of equity any single position may take.',
    unit: 'percent',
    group: 'Execution',
  },
  execution_accuracy: {
    label: 'Execution accuracy',
    short:
      'Daily bars only: whether fills and stops are decided from the day bar alone, or by replaying that day minute by minute. Intraday bars already step through the session.',
    unit: 'choice',
    group: 'Execution',
  },
  fill_timing: {
    label: 'Fill timing',
    short:
      "When an order fills relative to the bar that signalled it. Filling at the signal bar's own close is optimistic unless the order really is market-on-close.",
    unit: 'choice',
    group: 'Execution',
  },
  min_holding_days: {
    label: 'Min holding days',
    short: 'Signal exits are ignored until a position has been held this long. Stops still fire.',
    unit: 'trading-days',
    group: 'Execution',
  },
  max_holding_days: {
    label: 'Max holding days',
    short:
      'A position is closed once held this long, whatever the signals say, at the first bar of that session.',
    unit: 'trading-days',
    group: 'Execution',
  },
  cooldown: {
    label: 'Cooldown',
    short:
      'After closing a ticker, wait this long before it may be entered again. Stops one choppy name monopolising the book.',
    unit: 'trading-days',
    group: 'Execution',
  },
  allow_shorts: {
    label: 'Allow shorts',
    short: 'Whether a bearish entry opens a short. Off, bearish entries are simply ignored.',
    unit: 'on-off',
    group: 'Execution',
  },
  stop_loss: {
    label: 'Stop loss',
    short: 'Close a position once it has fallen this far from its entry price.',
    unit: 'percent-of-price',
    group: 'Execution',
  },
  take_profit: {
    label: 'Take profit',
    short: 'Close a position once it has gained this much from its entry price.',
    unit: 'percent-of-price',
    group: 'Execution',
  },
  trailing_stop: {
    label: 'Trailing stop',
    short:
      'Close a position once it has fallen this far from its highest price since entry: a stop that follows the price up.',
    unit: 'percent-of-price',
    group: 'Execution',
  },
  atr_stop: {
    label: 'ATR stop',
    short:
      'A stop placed this many Average True Ranges below entry, so it widens for volatile names and tightens for quiet ones.',
    unit: 'atr-multiple',
    group: 'Execution',
  },
  atr: {
    label: 'ATR (Average True Range)',
    short:
      'The average bar-to-bar range including gaps over the period: how much the price typically moves in one bar.',
    unit: 'bars',
    group: 'Execution',
  },
  commission: {
    label: 'Commission',
    short: 'Broker fee charged on every fill, as a share of the trade value.',
    unit: 'basis-points',
    group: 'Execution',
  },
  slippage: {
    label: 'Slippage',
    short:
      'How much worse than the quoted price a fill is assumed to be: paid on the way in and on the way out.',
    unit: 'basis-points',
    group: 'Execution',
  },
  borrow_cost: {
    label: 'Short borrow',
    short: 'Yearly fee for borrowing shares to short, charged daily while a short is open.',
    unit: 'basis-points',
    group: 'Execution',
  },
  price_adjustment: {
    label: 'Price adjustment',
    short:
      'Whether past prices are restated for splits and dividends. Unadjusted, a 4-for-1 split looks like a 75% crash and fires false signals.',
    unit: 'choice',
    group: 'Execution',
  },

  // --- Strategy --------------------------------------------------------------
  entry_logic: {
    label: 'Entry logic',
    short:
      'How entry components combine: all must fire, any may, more than half, or a weighted total reaching the threshold.',
    unit: 'choice',
    group: 'Strategy',
  },
  exit_logic: {
    label: 'Exit logic',
    short: 'How exit components combine, the same choices as entry logic.',
    unit: 'choice',
    group: 'Strategy',
  },
  weighted_threshold: {
    label: 'Threshold',
    short:
      'Weighted logic only: the sum of the active components’ weights must reach this before the position opens or closes.',
    unit: 'ratio',
    group: 'Strategy',
  },
  agreement_window: {
    label: 'Agreement window',
    short:
      'Components may agree within this many bars rather than only on the same bar. 1 means "fired on this bar".',
    unit: 'bars',
    group: 'Strategy',
  },
  role_entry: {
    label: 'Entry',
    short: 'A component that opens positions when it fires.',
    group: 'Strategy',
  },
  role_exit: {
    label: 'Exit',
    short: 'A component that closes positions when it fires.',
    group: 'Strategy',
  },
  role_filter: {
    label: 'Filter',
    short:
      'A gate: entries are allowed only while it is open. It never opens or closes a position by itself.',
    group: 'Strategy',
  },
  warm_up: {
    label: 'Warm-up',
    short:
      'Bars loaded before the window starts so every indicator already has its full lookback on the first day. Nothing is traded or reported in the warm-up.',
    unit: 'bars',
    group: 'Strategy',
  },
  lookback: {
    label: 'Lookback',
    short: 'How many past bars an indicator reads to produce one value.',
    unit: 'bars',
    group: 'Strategy',
  },

  // --- Data ------------------------------------------------------------------
  bar_frequency: {
    label: 'Bars',
    short:
      'The size of one price bar the strategy reads and trades on: daily, 1 hour, 15 or 5 minutes. Indicator periods count these bars; holding periods count trading days.',
    unit: 'choice',
    group: 'Data',
  },
  universe: {
    label: 'Universe',
    short:
      'The tickers the strategy may trade. Each gets its own signals; the book is shared between them.',
    group: 'Data',
  },
  macro_series: {
    label: 'Macro series',
    short:
      'Market-wide data a rule reads alongside prices, such as the VIX from FRED. Loaded separately from stock prices.',
    group: 'Data',
  },
} satisfies Record<string, TermDefinition>;

export type TermId = keyof typeof TERMS;

export function term(id: TermId): TermDefinition {
  return TERMS[id];
}
