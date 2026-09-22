"""Pydantic v2 response models mirroring contracts/openapi.yaml exactly."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Dataset = Literal["sqlite", "warehouse"]
"""Which store answered. Two runs from different datasets are never directly
comparable, however identical their configuration."""


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    dataset: Dataset
    seeded: bool
    signal_count: int
    #: Whether this deployment demands a bearer token. The SPA reads it to
    #: decide whether to show a sign-in gate at all, so the local demo still
    #: boots straight into the app.
    auth_required: bool = True


class Instrument(BaseModel):
    symbol: str
    name: str
    currency: str
    # Synthetic-demo only: a generated instrument is built to follow a known
    # regime, which is what makes the demo assertable. Real ingested
    # instruments have no such label, so the field is nullable rather than
    # carrying a fabricated one.
    regime_profile: Literal["trending", "mean_reverting", "volatile", "mixed"] | None = None
    bar_count: int
    signal_count: int


class InstrumentList(BaseModel):
    total: int
    items: list[Instrument]


class PriceBar(BaseModel):
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class PriceBarList(BaseModel):
    total: int
    items: list[PriceBar]


class Signal(BaseModel):
    id: int
    symbol: str
    date: str
    rule_name: str
    rule_version: str
    parameters: dict[str, Any]
    direction: Literal["bullish", "bearish"]
    trigger_values: dict[str, Any]
    data_window_end: str


class SignalList(BaseModel):
    total: int
    items: list[Signal]


class Error(BaseModel):
    detail: str


# --- Model catalog and experiment runs (feature 005) -----------------------


class ParamSpec(BaseModel):
    name: str
    type: Literal["int", "float", "bool", "enum"]
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: list[Any] | None = None
    description: str = ""


class Model(BaseModel):
    name: str
    version: str
    parameters: list[ParamSpec]
    lookback_days: int
    scale_class: Literal["scale_free", "price_scaled"]
    direction_semantics: str
    # Catalogue metadata, so a builder can group and gate rules without
    # hardcoding anything about any of them (Constitution II).
    category: Literal[
        "trend", "momentum", "mean_reversion", "volatility", "volume", "fundamental"
    ] = "trend"
    summary: str = ""
    #: Which strategy slots this rule may fill. A rule that reports a regime
    #: rather than a tradeable event advertises ["filter"] only.
    roles: list[Literal["entry", "exit", "filter"]] = ["entry", "exit"]
    #: Fundamental concepts this rule cannot work without. Empty for every rule
    #: that reads only bars. The builder reports them so a user can be told
    #: which of their instruments will never trade before they run, not after
    #: (docs/FUNDAMENTALS.md §5.1).
    requires_facts: list[str] = []


class ModelList(BaseModel):
    total: int
    items: list[Model]


class RunRequest(BaseModel):
    """Either shape of run request.

    Exactly one of ``model_name``, ``strategy_id`` or ``strategy`` identifies
    what to run. The single-model form is unchanged and still supported; it is
    promoted internally into a one-rule strategy so there is one execution path
    and not a legacy branch that slowly stops matching the real one.
    """

    model_name: str | None = None
    model_version: str | None = None
    parameters: dict[str, Any] = {}
    symbols: list[str]
    start_date: str
    end_date: str
    strategy_id: str | None = None
    strategy: StrategyRequest | None = None
    #: Overrides the strategy's own execution criteria for this run only.
    execution: ExecutionConfigModel | None = None


class CorporateActionNotice(BaseModel):
    """A split or dividend inside a run's window. Reported, never applied:
    stored bars are unadjusted, so a split makes the series jump in a way that
    is an artefact rather than a market move."""

    instrument_id: int
    symbol: str
    ex_date: str
    action_type: Literal["split", "dividend"]
    split_ratio: float | None = None
    dividend: float | None = None


class RunCoverage(BaseModel):
    instruments_requested: int
    instruments_with_data: int
    instruments_full_warmup: int


class Run(BaseModel):
    id: str
    name: str | None = None
    model_name: str
    model_version: str
    parameters: dict[str, Any]
    symbols: list[str]
    start_date: str
    end_date: str
    status: Literal["completed", "failed"]
    error: str | None = None
    created_at: str
    signal_count: int
    coverage: RunCoverage
    dataset: Dataset
    instrument_ids: list[int] | None = None
    ingest_run_ids: list[int] | None = None
    corporate_actions: list[CorporateActionNotice] = []
    re_runnable: bool = True
    model_available: bool = True
    # The strategy and criteria that actually ran, and what the engine did with
    # them. Null on runs recorded before either existed.
    strategy: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    execution_summary: ExecutionSummaryModel | None = None


class RunList(BaseModel):
    total: int
    items: list[Run]


class ExperimentSignal(BaseModel):
    symbol: str
    date: str
    direction: Literal["bullish", "bearish"]
    trigger_values: dict[str, Any]
    data_window_end: str
    #: Whether this opens a position, closes one, or both. "both" is what a
    #: single-model run produces, and is what rows recorded before strategies
    #: existed mean.
    kind: Literal["entry", "exit", "both"] = "both"


class RunDetail(Run):
    signals: list[ExperimentSignal]


class RunNameRequest(BaseModel):
    name: str


class EquityPoint(BaseModel):
    date: str
    value: float


class Trade(BaseModel):
    symbol: str
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float
    return_pct: float
    open: bool
    side: Literal["long", "short"] = "long"
    qty: float = 0.0
    #: Why the position closed. "the strategy said so" and "the stop caught it"
    #: are different facts about a strategy, and averaging them into one win
    #: rate hides which one is doing the work.
    exit_reason: Literal[
        "signal", "stop_loss", "take_profit", "trailing_stop", "max_holding",
        "end_of_window",
    ] = "signal"
    pnl: float = 0.0
    fees: float = 0.0


class PerformanceMetrics(BaseModel):
    total_return: float
    # Null rather than 0.0 when undefined: a fabricated zero would read as
    # "measured, and mediocre" instead of "not measurable".
    sharpe_ratio: float | None = None
    max_drawdown: float
    win_rate: float | None = None
    trade_count: int
    winning_trades: int
    losing_trades: int


class CostBreakdown(BaseModel):
    commission: float = 0.0
    slippage: float = 0.0


class RunPerformance(BaseModel):
    run_id: str
    initial_capital: float
    equity: list[EquityPoint]
    benchmark: list[EquityPoint]
    metrics: PerformanceMetrics
    trades: list[Trade]
    # Carried in the payload so the caveats cannot be lost by a UI refactor,
    # and now generated from the execution criteria that actually ran -- so a
    # result can no longer claim "no transaction costs" while having charged
    # them.
    assumptions: list[str]
    costs: CostBreakdown = CostBreakdown()
    exit_reasons: dict[str, int] = {}


# --- Historical replay ------------------------------------------------------
#
# The SSE stream (GET /runs/{run_id}/replay/stream) is documented in the
# contract but carries no response_model -- its frames are the JSON form of
# quantlab.replay.engine's events, one `data: {json}\n\n` frame each.


class ReplaySummary(BaseModel):
    run_id: str
    days: int
    initial_cash: float
    final_equity: float
    total_return: float
    # Null rather than 0.0 when undefined, as in PerformanceMetrics.
    sharpe_ratio: float | None = None
    max_drawdown: float
    win_rate: float | None = None
    trade_count: int
    winning_trades: int
    losing_trades: int
    assumptions: list[str]
    exit_reasons: dict[str, int] | None = None
    total_commission: float = 0.0
    total_slippage: float = 0.0


# --- Identity ---------------------------------------------------------------


class Credentials(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    created_at: str


class SessionOut(BaseModel):
    user: UserOut
    token: str
    expires_at: str


# --- Strategies and execution ----------------------------------------------


class StrategyComponentModel(BaseModel):
    rule_name: str
    rule_version: str | None = None
    parameters: dict[str, Any] = {}
    role: Literal["entry", "exit", "filter"] = "entry"
    weight: float = 1.0
    invert: bool = False


class ExecutionConfigModel(BaseModel):
    """Mirrors quantlab.execution.ExecutionConfig.

    Deliberately permissive here and strict in the library: the dataclass
    validates, and its ValueError becomes a 422 naming the field. Duplicating
    the bounds as pydantic constraints would mean two places to change and one
    of them eventually forgotten.
    """

    initial_capital: float = 100_000.0
    position_sizing: Literal[
        "equal_weight", "fixed_fraction", "fixed_notional", "volatility_target"
    ] = "equal_weight"
    sizing_value: float | None = None
    max_positions: int | None = None
    max_position_pct: float = 1.0
    fill_timing: Literal["signal_close", "next_open"] = "signal_close"
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None
    atr_stop_multiple: float | None = None
    atr_period: int = 14
    max_holding_days: int | None = None
    min_holding_days: int = 0
    cooldown_days: int = 0
    allow_shorts: bool = False


class StrategyRequest(BaseModel):
    name: str
    description: str = ""
    components: list[StrategyComponentModel]
    entry_logic: Literal["all", "any", "majority", "weighted"] = "all"
    exit_logic: Literal["all", "any", "majority", "weighted"] = "any"
    entry_threshold: float = 1.0
    exit_threshold: float = 1.0
    combine_window_days: int = 1
    execution: ExecutionConfigModel = ExecutionConfigModel()


class Strategy(StrategyRequest):
    id: str
    owner_id: str | None = None
    created_at: str
    updated_at: str
    #: Legal but probably unintended: no exit component, an unreachable
    #: combination, filters gating shorts. Reported rather than refused.
    warnings: list[str] = []


class StrategyList(BaseModel):
    total: int
    items: list[Strategy]


class StrategyTemplate(StrategyRequest):
    id: str


class StrategyTemplateList(BaseModel):
    total: int
    items: list[StrategyTemplate]


class ExecutionSummaryModel(BaseModel):
    """What the engine did, including what it refused to do.

    The rejection counters matter as much as the fills: a strategy whose
    signals were mostly dropped for want of a free slot has not been tested,
    and without these it looks identical to one that signalled rarely.
    """

    orders: int = 0
    fills: int = 0
    rejected_no_cash: int = 0
    rejected_max_positions: int = 0
    rejected_cooldown: int = 0
    rejected_shorts_disabled: int = 0
    dropped_no_bar: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    #: Dates where the entry logic said both "long" and "short", and so said
    #: nothing. Neither side was taken.
    contradictions: int = 0


# --- Research: the company, the universe, the screen (docs/RESEARCH.md) -----


class FundamentalFact(BaseModel):
    """One filed number, with everything needed to judge whether to trust it.

    ``filed_at`` and ``days_stale`` are not decoration. They are the only
    columns that reveal a look-ahead: a naive join returns Caterpillar's
    quarter ending 2024-06-30 from a filing dated 2026-03-26, and nothing else
    in the row says so (docs/FUNDAMENTALS.md §2).
    """

    concept: str
    value: float
    period_start: str | None = None
    period_end: str
    filed_at: str
    days_stale: int
    #: Which period length this figure describes. A quarter's revenue and a
    #: year's are both "revenue", and a ratio built from the wrong one is off
    #: by roughly four.
    scope: Literal["instant", "quarter", "interim", "annual"] = "instant"
    #: ``filed_at < period_end``: 710 rows in the warehouse carry a filing date
    #: before the period they label. Surfaced rather than dropped -- discarding
    #: data for looking strange is how a dataset ends up clean and wrong.
    forward_dated: bool = False
    #: The row the point-in-time rule selects for this concept on the as-of
    #: date, so the inspector does not have to re-derive a choice already made.
    in_force: bool = True


class ConceptCoverage(BaseModel):
    concept: str
    instruments: int
    first_filed: str | None = None
    last_filed: str | None = None
    #: Which names have it. Enumerated so a coverage warning can be
    #: concept-exact rather than falling back to "has no fundamentals at all".
    symbols: list[str] = []


class FundamentalsCoverage(BaseModel):
    """What exists, before anything is run.

    64 of 644 instruments have no filings. A strategy with a fundamental filter
    over those names does not fail to find trades, it *cannot* trade, and the
    two are indistinguishable in a result -- so they are distinguished here,
    before the run (docs/FUNDAMENTALS.md §5.1).
    """

    instruments_total: int
    instruments_with_facts: int
    concepts: list[ConceptCoverage]
    symbols_with_facts: list[str] = []
    symbols_without_facts: list[str] = []


class CompanySignalCount(BaseModel):
    rule_name: str
    count: int
    last_date: str | None = None
    last_direction: Literal["bullish", "bearish"] | None = None


class CompanyOverview(BaseModel):
    """Everything filed about one name, as of a date.

    ``concepts_missing`` is carried rather than left to be inferred from a
    short ``facts`` list: a name that has never filed gross profit and one
    whose gross profit has not been refiled since 2019 produce the same absence
    on the page and are not the same fact.
    """

    symbol: str
    name: str
    exchange: str
    currency: str
    #: Blank on 607 of 644 catalogued names, and returned blank rather than
    #: invented -- a fabricated sector would license a peer comparison the
    #: catalogue cannot support (docs/RESEARCH.md §2).
    sector: str
    as_of: str
    first_bar: str | None = None
    last_bar: str | None = None
    last_close: float | None = None
    facts: list[FundamentalFact] = []
    concepts_available: list[str] = []
    concepts_missing: list[str] = []
    signals: list[CompanySignalCount] = []
    signal_total: int = 0


ScreenMetric = Literal[
    "pe", "pb", "roe", "leverage", "net_margin", "gross_margin", "current_ratio"
]
"""The ratios a screen can constrain, each derived from filed concepts.

The vocabulary lives here because the request has to validate against it;
which concepts each one needs, and how it is computed, live beside the rules
whose arithmetic it borrows (quantlab.storage.warehouse). A contract test holds
the two together.
"""


class ScreenMetricCoverage(BaseModel):
    """How much of the universe a metric could actually be computed for.

    Per metric, because coverage is not uniform: gross profit is filed by 237
    names against revenue's 376. A screen that silently returned the difference
    would read as "few companies qualified" when the truth is "most were never
    measured" (docs/RESEARCH.md §2).
    """

    metric: ScreenMetric
    measured: int
    universe: int
    requires: list[str]


class ScreenRow(BaseModel):
    symbol: str
    name: str
    #: Null where the inputs were not filed, or where a denominator was not
    #: positive -- distinct from a zero, and never sorted as one.
    values: dict[str, float | None] = {}


class ScreenResult(BaseModel):
    as_of: str
    universe: str
    universe_size: int
    rows: list[ScreenRow] = []
    coverage: list[ScreenMetricCoverage] = []
    sort_by: ScreenMetric | None = None
    #: Dropped for failing a constraint, as opposed to being unmeasured. The
    #: split is the whole point: one is a fact about companies, the other about
    #: the warehouse.
    excluded_by_constraint: int = 0
    excluded_unmeasured: int = 0


class UniverseSummary(BaseModel):
    name: str
    #: The snapshot's own capture date, not the date that was asked for.
    as_of: str
    size: int


class UniverseList(BaseModel):
    total: int
    items: list[UniverseSummary]


# RunRequest and Run reference StrategyRequest, ExecutionConfigModel and
# ExecutionSummaryModel, which are defined below them. Rebuilding here resolves
# those forward references now rather than on first request.
RunRequest.model_rebuild()
Run.model_rebuild()
RunDetail.model_rebuild()
