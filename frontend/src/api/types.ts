import type { Health, Model, ParamSpec, Run, RunDetail, RunPerformance, Trade } from './client';

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
  'fundamental',
] as const;

export type SignalCategory = (typeof SIGNAL_CATEGORIES)[number];

export const STRATEGY_ROLES = ['entry', 'exit', 'filter'] as const;

export type StrategyRole = (typeof STRATEGY_ROLES)[number];

/**
 * A declared parameter, plus the unit it is expressed in.
 *
 * `unit` is the whole of the fundamentals parameter story: a P/E bound is a
 * ratio, an ROE floor is a percentage and a growth threshold is a percentage,
 * and a form that renders three bare number boxes will be typed into wrongly
 * (FUNDAMENTALS §6). It is optional and is never guessed from a parameter's
 * name — an undeclared unit renders as a plain number, because inferring
 * "margin" means a fraction and silently dividing the typed value by 100 is
 * the one failure mode worse than an unlabelled box.
 */
export type ParamSpecV2 = ParamSpec & { unit?: ParamUnit | string | null };

/** A registry entry with the §2 additions applied. */
export type CatalogModel = Omit<Model, 'parameters'> & {
  parameters: ParamSpecV2[];
  category: SignalCategory | 'uncategorised';
  summary: string;
  roles: StrategyRole[];
  /**
   * The fundamental concepts this rule reads (FUNDAMENTALS §4).
   *
   * Empty for every technical rule, which is what makes it the honest test of
   * "is this a fundamental component?" — the category is presentation, this is
   * the data dependency, and it is what says which instruments can never trade.
   */
  requires_facts: string[];
};

/** What `/models` may actually answer with while the backend is mid-flight. */
export type RawCatalogModel = Omit<Model, 'parameters'> & {
  parameters: ParamSpecV2[];
} & Partial<Omit<CatalogModel, keyof Model>>;

export const CATEGORY_LABELS: Record<CatalogModel['category'], string> = {
  trend: 'Trend',
  momentum: 'Momentum',
  mean_reversion: 'Mean reversion',
  volatility: 'Volatility',
  volume: 'Volume',
  fundamental: 'Fundamentals',
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
  /**
   * Entries suppressed by a shut gate, split by what shut it.
   *
   * FUNDAMENTALS §6: without the split, a strategy whose fundamental filter
   * excluded every name looks identical to one that simply never signalled.
   * Both are optional — a backend that does not count them renders nothing
   * rather than a fabricated zero.
   */
  gated_by_fundamental?: number;
  gated_by_technical?: number;
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
  /** What the run's fundamental components could actually see (§5.1, §5.3). */
  fundamentals?: RunFundamentals | null;
};

/**
 * The fundamental half of a run's coverage, recorded by the run itself.
 *
 * Separate from `coverage` (which counts bars) because the two denominators
 * genuinely differ: an instrument can have sixteen years of prices and no
 * filings at all, and a run that reports only the first number is reporting
 * the wrong one for a strategy gated on the second.
 */
export interface RunFundamentals {
  instruments_requested: number;
  instruments_with_facts: number;
  /** The concepts the run loaded, from the rules' `requires_facts`. */
  concepts?: string[];
  /** The names that had no fact at all, and so could never trade. */
  symbols_without_facts?: string[];
  /** Fact lineage, the counterpart of the bar `ingest_run_ids` (§5.3). */
  ingest_run_ids?: string[];
}

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

// --- Fundamentals (docs/FUNDAMENTALS.md) -----------------------------------

/**
 * The units a declared parameter can be expressed in.
 *
 * `fraction` and `percent` are deliberately two different things: a fraction
 * is 0.15 on the wire and 15% on the screen, a percent is 15 in both. Which
 * one a rule uses is the rule's business; getting it wrong by a factor of 100
 * is the exact failure the execution form already avoids for stops and
 * targets, and this is that mechanism made general.
 */
export const PARAM_UNITS = [
  'ratio',
  'percent',
  'fraction',
  'currency',
  'days',
  'quarters',
  'sigma',
  'count',
] as const;

export type ParamUnit = (typeof PARAM_UNITS)[number];

export interface UnitPresentation {
  /** Shown beside the field, in the same place the execution form puts USD. */
  suffix: string;
  /** One line under the field saying what the number means. */
  help: string;
  /**
   * Multiplier from the wire value to the displayed one.
   *
   * 100 for a fraction (0.15 → 15), 1 for everything else. Rendering is the
   * only thing that scales; what the draft holds and sends to the engine is
   * always the wire value.
   */
  scale: number;
  /** How the value reads inside the plain-English sentence. */
  inSentence: (display: string) => string;
}

export const UNIT_PRESENTATION: Record<ParamUnit, UnitPresentation> = {
  ratio: {
    suffix: '×',
    help: 'A ratio, not a percentage: 20 means twenty times.',
    scale: 1,
    inSentence: (value) => `${value}×`,
  },
  percent: {
    suffix: '%',
    help: 'A percentage, entered and stored as one: 15 means 15%.',
    scale: 1,
    inSentence: (value) => `${value}%`,
  },
  fraction: {
    suffix: '%',
    help: 'A percentage. Entered as 15, sent to the engine as 0.15.',
    scale: 100,
    inSentence: (value) => `${value}%`,
  },
  currency: {
    suffix: 'USD',
    help: 'A cash amount, in the reporting currency of the filing.',
    scale: 1,
    inSentence: (value) => `${value} USD`,
  },
  days: {
    suffix: 'days',
    help: 'Calendar days.',
    scale: 1,
    inSentence: (value) => `${value} days`,
  },
  quarters: {
    suffix: 'qtrs',
    help: 'Reported quarters, not bars.',
    scale: 1,
    inSentence: (value) => `${value} quarters`,
  },
  sigma: {
    suffix: 'σ',
    help: 'Standard deviations from the series’ own trend.',
    scale: 1,
    inSentence: (value) => `${value}σ`,
  },
  count: { suffix: '', help: 'A plain count.', scale: 1, inSentence: (value) => value },
};

export function unitOf(spec: ParamSpecV2): ParamUnit | null {
  const declared = spec.unit;
  return typeof declared === 'string' && (PARAM_UNITS as readonly string[]).includes(declared)
    ? (declared as ParamUnit)
    : null;
}

/**
 * One filed fact, as `GET /instruments/{symbol}/fundamentals?as_of=` serves it.
 *
 * `filed_at` is the only field that answers "when could I have known this?".
 * `period_end` answers "what period is this?", and answering the first with
 * the second is the mistake the whole feature exists to avoid (§2).
 *
 * `days_stale` arrives from the server. It is not recomputed here: a staleness
 * the browser derived from two dates it happened to have would be a second
 * implementation of the PIT rule, and the second one is the one that drifts.
 */
export interface FundamentalFact {
  concept: string;
  value: number;
  period_start: string | null;
  period_end: string;
  filed_at: string;
  days_stale: number;
  /** As filed: USD, shares, pure. Displayed, never converted. */
  unit?: string | null;
  /** The filing this row came from — what makes a restatement identifiable. */
  accession?: string | null;
  /**
   * The row the PIT rule selects for this concept on the as-of date.
   *
   * Sent by the server when it knows; when it is absent the inspector falls
   * back to the rule in §2 as an ordering (greatest `period_end`, then
   * greatest `filed_at`), which is a selection, not a calculation.
   */
  in_force?: boolean;
}

/** One concept's real coverage window, read from the warehouse (§5.2). */
export interface ConceptCoverage {
  concept: string;
  /** How many instruments have at least one fact for it. */
  instruments: number;
  first_filed: string | null;
  last_filed: string | null;
  /**
   * The instruments that have it, when the server is willing to enumerate
   * them. Present means the coverage warning can be concept-exact; absent
   * means it falls back to "has no fundamentals at all", and says so.
   */
  symbols?: string[];
}

/**
 * `GET /fundamentals/coverage`: what exists, before anything is run.
 *
 * The one figure this cannot do without is which names have nothing: 64 of
 * 644 instruments have no filings, and a strategy with a fundamental filter
 * over those names *cannot* trade rather than failing to find trades (§5.1).
 * The two are indistinguishable in a result, so they have to be distinguished
 * before the run.
 */
export interface FundamentalsCoverage {
  instruments_total: number;
  instruments_with_facts: number;
  concepts: ConceptCoverage[];
  /** Names with at least one fact of any concept. */
  symbols_with_facts?: string[];
  /** Names with none. Preferred over deriving it, when the server sends it. */
  symbols_without_facts?: string[];
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
    // No fallback guess: a rule that declares nothing reads no facts, and
    // claiming otherwise would put a coverage warning on a strategy that has
    // no fundamental component in it.
    requires_facts: (model.requires_facts ?? []).filter(
      (concept): concept is string => typeof concept === 'string',
    ),
  };
}

/** Merge a partial execution config onto the contract's declared defaults. */
export function withExecutionDefaults(partial?: Partial<ExecutionConfig> | null): ExecutionConfig {
  return { ...DEFAULT_EXECUTION, ...(partial ?? {}) };
}
