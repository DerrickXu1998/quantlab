import type { Health, Model, Run, RunDetail, RunPerformance, Trade } from './client';

/**
 * Hand-written types for the surfaces added by `docs/CONTRACT_V2.md`.
 *
 * `schema.d.ts` is generated from the OpenAPI document by `npm run gen:api`
 * and must not be hand-edited, so the identity, strategy and execution shapes
 * live here until the generator catches up. Everything below is declared as an
 * *extension* of the generated type it augments — `CatalogModel = Model & …` —
 * so the day the spec regenerates, deleting a line here is the whole migration
 * and nothing silently diverges in the meantime.
 *
 * The new fields are optional wherever the contract calls them additive: a run
 * recorded before the change carries no `execution`, and a backend that has not
 * shipped §2 yet answers `/models` without `roles`. The normalisers at the
 * bottom are what keep those two cases out of every component.
 */

// --- §1 Identity -----------------------------------------------------------

export interface AuthUser {
  id: string;
  email: string;
  created_at: string;
}

export interface AuthSession {
  user: AuthUser;
  token: string;
  /** ISO-8601. The server revokes on logout; this is only for display. */
  expires_at: string;
}

export interface Credentials {
  email: string;
  password: string;
}

/**
 * `/health` gains `auth_required`. It is optional here because a backend that
 * predates §1 does not send it, and the gate must fail *open* in that case —
 * the field is a disclosure about the API, not a permission check, and the
 * real enforcement is the 401 on every protected route.
 */
export type HealthV2 = Health & { auth_required?: boolean };

// --- §2 Signals ------------------------------------------------------------

export const SIGNAL_CATEGORIES = [
  'trend',
  'momentum',
  'mean_reversion',
  'volatility',
  'volume',
] as const;

export type SignalCategory = (typeof SIGNAL_CATEGORIES)[number];

export const STRATEGY_ROLES = ['entry', 'exit', 'filter'] as const;

export type StrategyRole = (typeof STRATEGY_ROLES)[number];

/** A registry entry with the §2 additions applied. */
export type CatalogModel = Model & {
  category: SignalCategory | 'uncategorised';
  summary: string;
  roles: StrategyRole[];
};

/** What `/models` may actually answer with while the backend is mid-flight. */
export type RawCatalogModel = Model & Partial<Omit<CatalogModel, keyof Model>>;

export const CATEGORY_LABELS: Record<CatalogModel['category'], string> = {
  trend: 'Trend',
  momentum: 'Momentum',
  mean_reversion: 'Mean reversion',
  volatility: 'Volatility',
  volume: 'Volume',
  uncategorised: 'Uncategorised',
};

export const ROLE_LABELS: Record<StrategyRole, string> = {
  entry: 'Entry',
  exit: 'Exit',
  filter: 'Filter',
};

/** One line each, shown where a user first meets the word. */
export const ROLE_EXPLAINERS: Record<StrategyRole, string> = {
  entry: 'Opens a position when it fires.',
  exit: 'Closes an open position when it fires.',
  filter: 'Never opens or closes anything — it only permits entries while it is true.',
};

// --- §3 Strategies ---------------------------------------------------------

export const COMBINE_LOGICS = ['all', 'any', 'majority', 'weighted'] as const;

export type CombineLogic = (typeof COMBINE_LOGICS)[number];

export interface StrategyComponent {
  rule_name: string;
  /** Omitted means "the latest registered version". */
  rule_version?: string;
  parameters: Record<string, unknown>;
  role: StrategyRole;
  /** Only read by `weighted` logic. */
  weight?: number;
  /** Swap this component's bullish and bearish directions. */
  invert?: boolean;
}

/** The body of a create/replace, and the inline `strategy` on a run request. */
export interface StrategySpec {
  name: string;
  description?: string;
  components: StrategyComponent[];
  entry_logic: CombineLogic;
  exit_logic: CombineLogic;
  entry_threshold?: number;
  exit_threshold?: number;
  combine_window_days: number;
  execution?: ExecutionConfig;
}

/** A stored strategy: the spec plus the server's own columns. */
export type Strategy = StrategySpec & {
  id: string;
  /** Null in single-user mode, where requests bind to the built-in local user. */
  owner_id: string | null;
  created_at: string;
  updated_at: string;
  /**
   * The server's own read of the saved spec: legal but probably unintended
   * shapes, reported rather than refused. Optional because the contract does
   * not list it -- see the report accompanying this change.
   */
  warnings?: string[];
};

export interface StrategyList {
  total: number;
  items: Strategy[];
}

/**
 * A starter strategy, served by `GET /strategy-templates`.
 *
 * The same shape as a strategy spec plus a stable id, and deliberately not a
 * stored strategy: it has no owner and no timestamps because nobody owns it
 * until they save a copy.
 */
export type StrategyTemplate = StrategySpec & { id: string };

export interface StrategyTemplateList {
  total: number;
  items: StrategyTemplate[];
}

// --- §4 Execution criteria -------------------------------------------------

export const POSITION_SIZING_MODES = [
  'equal_weight',
  'fixed_fraction',
  'fixed_notional',
  'volatility_target',
] as const;

export type PositionSizing = (typeof POSITION_SIZING_MODES)[number];

export const FILL_TIMINGS = ['signal_close', 'next_open'] as const;

export type FillTiming = (typeof FILL_TIMINGS)[number];

export interface ExecutionConfig {
  initial_capital: number;

  position_sizing: PositionSizing;
  /** Fraction of equity | notional per trade | target annual vol. Mode-dependent. */
  sizing_value: number | null;
  max_positions: number | null;
  max_position_pct: number;

  fill_timing: FillTiming;
  commission_bps: number;
  slippage_bps: number;

  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  trailing_stop_pct: number | null;
  atr_stop_multiple: number | null;
  atr_period: number;

  max_holding_days: number | null;
  min_holding_days: number;
  cooldown_days: number;

  allow_shorts: boolean;
}

/** The contract's own defaults, §4, field for field. */
export const DEFAULT_EXECUTION: ExecutionConfig = {
  initial_capital: 100000,
  position_sizing: 'equal_weight',
  sizing_value: null,
  max_positions: null,
  max_position_pct: 1,
  fill_timing: 'signal_close',
  commission_bps: 0,
  slippage_bps: 0,
  stop_loss_pct: null,
  take_profit_pct: null,
  trailing_stop_pct: null,
  atr_stop_multiple: null,
  atr_period: 14,
  max_holding_days: null,
  min_holding_days: 0,
  cooldown_days: 0,
  allow_shorts: false,
};

/** Which sizing modes read `sizing_value`, and what it means to each. */
export const SIZING_VALUE_MEANING: Partial<Record<PositionSizing, string>> = {
  fixed_fraction: 'Fraction of equity committed to each position (0.1 = 10%).',
  fixed_notional: 'Cash amount put into each position, regardless of equity.',
  volatility_target: 'Target annualised volatility; the size is scaled to hit it.',
};

// --- §5 Runs ---------------------------------------------------------------

export const EXIT_REASONS = [
  'signal',
  'stop_loss',
  'take_profit',
  'trailing_stop',
  'max_holding',
  'end_of_window',
] as const;

export type ExitReason = (typeof EXIT_REASONS)[number];

export const EXIT_REASON_LABELS: Record<ExitReason, string> = {
  signal: 'Signal',
  stop_loss: 'Stop loss',
  take_profit: 'Take profit',
  trailing_stop: 'Trailing stop',
  max_holding: 'Max holding',
  end_of_window: 'End of window',
};

/**
 * What the engine did, including what it refused to do.
 *
 * The contract names four counters; the engine reports several more, and they
 * are the ones that matter most. A run whose entries were nearly all rejected
 * for want of a free slot, or because shorts were switched off, has not really
 * been tested — and without these it looks identical to a strategy that simply
 * signalled rarely. They are optional here because the contract does not list
 * them, so a backend at the documented shape still reads.
 */
export interface ExecutionSummary {
  orders: number;
  fills: number;
  rejected_no_cash: number;
  dropped_no_bar: number;
  total_commission: number;
  total_slippage: number;
  rejected_max_positions?: number;
  rejected_cooldown?: number;
  rejected_shorts_disabled?: number;
  /** Entry and exit both firing on one bar for one symbol. */
  contradictions?: number;
}

/** Per-trade detail gained in §5. Every field is additive and so optional. */
export type TradeV2 = Trade & {
  side?: 'long' | 'short';
  qty?: number;
  exit_reason?: ExitReason | null;
  pnl?: number | null;
  fees?: number | null;
};

export type RunPerformanceV2 = Omit<RunPerformance, 'trades'> & {
  trades: TradeV2[];
  costs?: { commission: number; slippage: number } | null;
  exit_reasons?: Partial<Record<ExitReason, number>> | null;
};

/** Runs recorded before the change carry none of these — hence nullable. */
export type RunV2 = Run & {
  strategy?: Strategy | StrategySpec | null;
  execution?: ExecutionConfig | null;
  execution_summary?: ExecutionSummary | null;
};

/**
 * A run list carries the same additions as a run detail: the server serialises
 * one `Run` model for both. Typed separately from the generated `RunList`
 * because the generator still reflects the pre-strategy contract.
 */
export type RunListV2 = { total: number; items: RunV2[] };

/** The same additions on the detail read, which carries the signal list too. */
export type RunDetailV2 = RunDetail & Omit<RunV2, keyof Run>;

/** The §5 strategy-shaped run request. Legacy `model_name` is unchanged. */
export interface StrategyRunRequest {
  strategy_id?: string;
  strategy?: StrategySpec;
  execution?: ExecutionConfig;
  symbols: string[];
  start_date: string;
  end_date: string;
}

// --- Normalisers -----------------------------------------------------------

/**
 * Fill in the §2 fields a pre-change backend does not send.
 *
 * The fallback for `roles` is entry+exit rather than all three: claiming a
 * rule can be used as a filter when the server never said so would let the
 * builder assemble a strategy the server then rejects, and a rejection after
 * the fact is a worse answer than a narrower catalogue.
 */
export function asCatalogModel(model: RawCatalogModel): CatalogModel {
  const roles = (model.roles ?? []).filter((role): role is StrategyRole =>
    (STRATEGY_ROLES as readonly string[]).includes(role),
  );
  return {
    ...model,
    category: model.category ?? 'uncategorised',
    summary: model.summary ?? model.direction_semantics,
    roles: roles.length > 0 ? roles : ['entry', 'exit'],
  };
}

/** Merge a partial execution config onto the contract's declared defaults. */
export function withExecutionDefaults(partial?: Partial<ExecutionConfig> | null): ExecutionConfig {
  return { ...DEFAULT_EXECUTION, ...(partial ?? {}) };
}
