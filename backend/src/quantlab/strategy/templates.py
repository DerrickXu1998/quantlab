"""Starter strategies: the onboarding path.

A blank strategy builder is a wall. Somebody who wants "an RSI strategy" needs
to see one working before the twenty knobs mean anything, and copying a
template that already trades is a far better first move than assembling one
from parts and discovering it never fires.

These are deliberately *complete* -- entry, exit, filters, stops, costs -- and
deliberately unexceptional. They are starting points to be modified, not
recommendations; none of them has been validated out of sample, and the numbers
here were chosen to be conventional and legible rather than optimal. Tuning
them against a backtest until they look good is exactly the overfitting the
strategy guide warns about.

Each carries realistic costs. A template that shipped with zero commission
would teach a new user that turnover is free, which is the single most
expensive lesson to unlearn.
"""

from __future__ import annotations

from quantlab.execution.config import ExecutionConfig
from quantlab.strategy.spec import StrategyComponent, StrategySpec

#: 5 bps commission and 2 bps slippage: a plausible retail-to-institutional
#: round trip on a liquid name. Cheap, but not free.
_COSTS = {"commission_bps": 5.0, "slippage_bps": 2.0}


def _component(rule: str, role: str, **parameters) -> StrategyComponent:
    return StrategyComponent(rule_name=rule, role=role, parameters=parameters)


def _rsi_mean_reversion() -> StrategySpec:
    return StrategySpec(
        name="RSI mean reversion",
        description=(
            "Buy a name that has been sold off and is starting to recover -- RSI "
            "coming back up through 30 -- and let it go when RSI comes back down "
            "through 70. The stop is what keeps this honest: a name can be oversold "
            "and keep falling for months, and without a stop this strategy will hold "
            "it the whole way down."
        ),
        components=(
            _component("rsi-threshold", "entry", period=14, oversold=30.0, overbought=70.0),
            _component("rsi-threshold", "exit", period=14, oversold=30.0, overbought=70.0),
        ),
        entry_logic="any",
        exit_logic="any",
        execution=ExecutionConfig(
            stop_loss_pct=0.08,
            take_profit_pct=0.15,
            max_holding_days=60,
            **_COSTS,
        ),
    )


def _macd_trend_following() -> StrategySpec:
    return StrategySpec(
        name="MACD trend following",
        description=(
            "Follow momentum: go long when the MACD line crosses above its signal "
            "line, close when it crosses back. The ADX filter is doing the real work "
            "-- MACD crossovers in a sideways market are noise, and the filter drops "
            "the ones that fire when there is no trend to follow. A trailing stop "
            "rather than a fixed target, because the point of trend following is to "
            "let the winners run."
        ),
        components=(
            _component("macd-crossover", "entry", fast=12, slow=26, signal=9),
            _component("macd-crossover", "exit", fast=12, slow=26, signal=9),
            _component("adx-trend-filter", "filter", period=14, threshold=25.0),
        ),
        entry_logic="any",
        exit_logic="any",
        execution=ExecutionConfig(
            trailing_stop_pct=0.12,
            min_holding_days=3,
            **_COSTS,
        ),
    )


def _donchian_breakout() -> StrategySpec:
    return StrategySpec(
        name="Donchian breakout with trend and volume filters",
        description=(
            "The classic turtle shape: buy a 20-session high, leave on a 10-session "
            "low. Asymmetric on purpose -- slow to enter, quick to leave. Two filters "
            "drop the weakest breakouts: ADX requires a trend to already exist, and "
            "the volume filter requires somebody to have actually participated in the "
            "break. The ATR stop sizes the risk to the instrument's own volatility "
            "instead of applying one percentage to names that move very differently."
        ),
        components=(
            _component("donchian-breakout", "entry", entry_window=20, exit_window=10),
            _component("donchian-breakout", "exit", entry_window=20, exit_window=10),
            _component("adx-trend-filter", "filter", period=14, threshold=20.0),
            _component("volume-spike", "filter", window=20, multiple=1.3),
        ),
        entry_logic="any",
        exit_logic="any",
        execution=ExecutionConfig(
            atr_stop_multiple=2.5,
            atr_period=14,
            max_positions=5,
            position_sizing="fixed_fraction",
            sizing_value=0.20,
            **_COSTS,
        ),
    )


def _dual_confirmation() -> StrategySpec:
    return StrategySpec(
        name="Dual-confirmation reversion",
        description=(
            "Requires two independent things to agree before entering: the close "
            "back inside the lower Bollinger band, and RSI recovering out of oversold. "
            "The three-session agreement window matters -- demanding that two "
            "oscillators turn on the same bar means this would almost never trade. "
            "Exits on the z-score reverting to the mean, with a holding limit so a "
            "position that simply goes quiet does not sit in the book forever."
        ),
        components=(
            _component("bollinger-reversion", "entry", window=20, num_std=2.0),
            _component("rsi-threshold", "entry", period=14, oversold=35.0, overbought=70.0),
            _component("zscore-reversion", "exit", window=20, threshold=1.0),
        ),
        entry_logic="all",
        exit_logic="any",
        combine_window_days=3,
        execution=ExecutionConfig(
            stop_loss_pct=0.06,
            max_holding_days=30,
            position_sizing="fixed_fraction",
            sizing_value=0.25,
            max_positions=4,
            **_COSTS,
        ),
    )


# ---------------------------------------------------------------------------
# AI-Quant-Book presets (docs/AI_QUANT_BOOK_STRATEGY_PLAN.md, S1/S2/S6/S7)
#
# The book's recommended baseline before any model: rules-based regime
# routing. S1 and S2 are the two halves -- the same ADX gate, one of them
# inverted -- so between them a trending name is only ever traded by the trend
# strategy and a ranging one only by the reversion strategy. Each description
# states the failure mode the book predicts, because a backtest that does
# *not* fail where the book says it should is a bug signal, not a win.
#
# All of these run on unadjusted bars (data gap D3): a split inside the window
# is a price gap, and a trend or reversion rule can fire on it. Check trades on
# split dates before trusting a long-horizon result.
# ---------------------------------------------------------------------------

#: The ADX gate shared by S1 (as is) and S2 (inverted). Kept as one value so
#: the two halves of the router can never drift apart.
_TREND_ADX = 25.0
_RANGE_ADX = 20.0


def _regime_trend() -> StrategySpec:
    return StrategySpec(
        name="S1 · Regime-gated trend following",
        description=(
            "Trade moving-average crosses only when ADX says a trend exists "
            f"(ADX > {_TREND_ADX:g}); stand aside in ranges. Sized to a volatility "
            "budget per name, with a 2x ATR stop so each position risks about the "
            "same in its own terms. Expect a 30-45% win rate carried by a few large "
            "winners, and expect it to bleed in sideways years (2015, 2022) -- that "
            "is the book's prediction, and a good falsification test."
        ),
        components=(
            _component("sma-crossover", "entry", fast=20, slow=50),
            _component("sma-crossover", "exit", fast=20, slow=50),
            _component("adx-trend-filter", "filter", period=14, threshold=_TREND_ADX),
        ),
        entry_logic="all",
        exit_logic="any",
        execution=ExecutionConfig(
            position_sizing="volatility_target",
            sizing_value=0.02,
            max_positions=10,
            max_position_pct=0.15,
            atr_stop_multiple=2.0,
            atr_period=14,
            **_COSTS,
        ),
    )


def _regime_reversion() -> StrategySpec:
    return StrategySpec(
        name="S2 · Regime-gated mean reversion",
        description=(
            "Buy a close back inside the lower Bollinger band, but only while RSI is "
            f"still low and the name is ranging -- the ADX gate inverted (ADX < "
            f"{_RANGE_ADX:g}). The gap between {_RANGE_ADX:g} and {_TREND_ADX:g} is "
            "deliberate: an ambiguous regime belongs to neither strategy. Reversion "
            "trades are short-lived, so they are held ten sessions at most, behind a "
            "hard stop at 2x ATR -- the book's mandatory stop, scaled to each name's "
            "own noise. Expect a 55-70% win rate with small wins, and expect "
            "breakouts to hurt; the stop is what keeps one from becoming a disaster."
        ),
        components=(
            _component("bollinger-reversion", "entry", window=20, num_std=2.0),
            _component("zscore-reversion", "exit", window=20, threshold=1.0),
            # A confirmation, not a second oversold test: the band re-entry is
            # already that. 45 keeps "still weak" without halving the trades
            # (ceiling 40 cut entries from 159 to 85 on 8 names over 2015-26).
            _component("rsi-zone", "filter", period=14, floor=0.0, ceiling=45.0),
            StrategyComponent(
                rule_name="adx-trend-filter",
                role="filter",
                parameters={"period": 14, "threshold": _RANGE_ADX},
                invert=True,
            ),
        ),
        entry_logic="all",
        exit_logic="any",
        execution=ExecutionConfig(
            position_sizing="fixed_fraction",
            sizing_value=0.10,
            max_positions=8,
            # ATR, not a fixed 4%: on 60 US names 2015-26 a 4% stop sat inside
            # ordinary daily noise and closed 435 of 907 trades (46% win rate,
            # outside the book's 55-70%). 2x ATR restored 58% -- the predicted
            # shape -- without being tuned for return.
            atr_stop_multiple=2.0,
            atr_period=14,
            take_profit_pct=0.05,
            max_holding_days=10,
            **_COSTS,
        ),
    )


def _macro_gated_trend() -> StrategySpec:
    base = _regime_trend()
    return StrategySpec(
        name="S6 · Macro-gated trend following",
        description=(
            "S1 with a portfolio-wide risk-off switch: no new entries on any name "
            "while VIX is above 30. Exits are never blocked by the gate, so a crisis "
            "can only stop the book adding risk, not trap it in positions. Compare it "
            "with plain S1 over 2020 and 2022 -- the gate should cost a little in calm "
            "years and save more in the crashes. Needs VIX.FRED in the store."
        ),
        components=(
            *base.components,
            _component("macro-risk-off", "filter", vix_max=30.0),
        ),
        entry_logic="all",
        exit_logic="any",
        execution=base.execution,
    )


def _quality_momentum() -> StrategySpec:
    return StrategySpec(
        name="S7 · Quality + momentum composite",
        description=(
            "Stack features from different families so their decay is not "
            "correlated. Value and quality are gates: P/E at most 30, ROE at least "
            "12%, operating margin at least 10%. The trigger needs two of three "
            "families to agree within a month -- a 3-month momentum cross, "
            "revenue growth, or margin expansion. The fundamental triggers compare "
            "annual filings, so they fire about once a year per name, on the day "
            "the report becomes visible: expect few trades, clustered after "
            "reporting season. Fundamentals are point-in-time, and a name with no "
            "filings never qualifies."
        ),
        components=(
            _component("roc-momentum", "entry", period=63, upper=10.0, lower=-10.0),
            _component("revenue-growth", "entry", threshold=0.05),
            _component("margin-expansion", "entry", periods=2),
            _component("roc-momentum", "exit", period=63, upper=10.0, lower=-10.0),
            _component("pe-filter", "filter", min_pe=0.0, max_pe=30.0),
            _component("profitability-filter", "filter", min_roe=0.12),
            _component("margin-filter", "filter", min_margin=0.10),
        ),
        # Weighted with equal weights and a threshold of 2: "any two of three".
        entry_logic="weighted",
        entry_threshold=2.0,
        exit_logic="any",
        # One month for the families to agree. A quarter (63) kept the
        # agreement alive long after a position closed and re-entered it:
        # 1,887 trades and 36k of costs on 60 names 2015-26, against 327 and 6k.
        combine_window_days=21,
        execution=ExecutionConfig(
            position_sizing="fixed_fraction",
            sizing_value=0.10,
            max_positions=10,
            trailing_stop_pct=0.15,
            **_COSTS,
        ),
    )


# ---------------------------------------------------------------------------
# Robert Carver, Systematic Trading (Bookey summary supplied by the user).
#
# Carver's EWMAC produces continuous, volatility-normalized forecasts. The
# strategy engine combines events instead, so these candidates use agreement
# across EMA-crossover speeds as an explicit approximation, not as a claim to
# implement forecast scalars or diversification multipliers. Volatility-targeted
# sizing, several instruments, next-open fills and non-zero costs retain the
# book's risk and turnover discipline. A carry candidate is deliberately absent:
# this store has no dividend-yield, funding-rate or futures-curve series.
# ---------------------------------------------------------------------------

_EWMAC_WINDOWS = ((8, 32), (16, 64), (32, 128))


def _ewmac_ensemble(name: str, description: str, execution: ExecutionConfig) -> StrategySpec:
    components = tuple(
        component
        for fast, slow in _EWMAC_WINDOWS
        for component in (
            _component("ema-crossover", "entry", fast=fast, slow=slow),
            _component("ema-crossover", "exit", fast=fast, slow=slow),
        )
    )
    return StrategySpec(
        name=name,
        description=description,
        components=components,
        entry_logic="majority",
        exit_logic="majority",
        combine_window_days=5,
        execution=execution,
    )


def _systematic_ewmac_long() -> StrategySpec:
    return _ewmac_ensemble(
        name="test-candidate-systematic-1",
        description=(
            "Carver-inspired diversified EWMAC: two of three trend speeds (8/32, "
            "16/64 and 32/128 sessions) must agree within five sessions to enter "
            "or exit. Event voting approximates the book's combined forecasts; it "
            "does not implement continuous forecast scalars. Positions are sized "
            "to a 2% annualised volatility contribution, capped per name, filled "
            "at the next open and charged costs. Long-only research candidate, "
            "not a fitted or out-of-sample-validated recommendation."
        ),
        execution=ExecutionConfig(
            position_sizing="volatility_target",
            sizing_value=0.02,
            max_positions=10,
            max_position_pct=0.15,
            fill_timing="next_open",
            **_COSTS,
        ),
    )


def _systematic_ewmac_long_short() -> StrategySpec:
    return _ewmac_ensemble(
        name="test-candidate-systematic-2",
        description=(
            "The multi-speed EWMAC ensemble traded in both directions: majority "
            "bullish agreement opens a long, majority bearish agreement opens a "
            "short, and the opposite majority closes it. This is an event-based "
            "approximation of Carver's combined forecasts. A lower volatility "
            "target and position cap limit risk; shorts pay 50 bps annual borrow, "
            "though locate availability remains unmodelled. Next-open fills and "
            "transaction costs apply. Research candidate, not a validated system."
        ),
        execution=ExecutionConfig(
            position_sizing="volatility_target",
            sizing_value=0.015,
            max_positions=10,
            max_position_pct=0.10,
            fill_timing="next_open",
            allow_shorts=True,
            borrow_cost_bps=50.0,
            **_COSTS,
        ),
    )


def _systematic_quality_value() -> StrategySpec:
    return StrategySpec(
        name="test-candidate-systematic-3",
        description=(
            "A simple ideas-first quality/value trend candidate. A 16/64 EWMAC "
            "cross enters only while filed accounts show ROE of at least 10%, "
            "long-term debt no greater than equity, P/E between 0 and 30, and P/B "
            "between 0 and 4; the opposite cross exits. Every fundamental is "
            "point-in-time by filing date, and missing or stale facts keep the "
            "gate shut, so coverage will vary by symbol. Volatility-targeted "
            "sizing, next-open fills and costs follow Carver's risk discipline."
        ),
        components=(
            _component("ema-crossover", "entry", fast=16, slow=64),
            _component("ema-crossover", "exit", fast=16, slow=64),
            _component("profitability-filter", "filter", min_roe=0.10),
            _component("leverage-filter", "filter", max_ratio=1.0),
            _component("pe-filter", "filter", min_pe=0.0, max_pe=30.0),
            _component("pb-filter", "filter", min_pb=0.0, max_pb=4.0),
        ),
        entry_logic="all",
        exit_logic="any",
        execution=ExecutionConfig(
            position_sizing="volatility_target",
            sizing_value=0.02,
            max_positions=10,
            max_position_pct=0.15,
            fill_timing="next_open",
            **_COSTS,
        ),
    )


def _systematic_cash_backed_growth() -> StrategySpec:
    return StrategySpec(
        name="test-candidate-systematic-4",
        description=(
            "Combine market and filing evidence: any two of a 16/64 EWMAC cross, "
            "annual revenue growth of at least 5%, and operating cash flow "
            "exceeding earnings by at least 25% must agree within 21 sessions. "
            "ROE and leverage gates exclude weak or highly geared issuers. An "
            "EWMAC reversal or cash flow falling short of earnings exits. Filing "
            "signals fire only when public, never on their period end; sparse "
            "coverage and reporting-season clustering are expected. Volatility "
            "targeting, next-open fills and costs limit risk and turnover."
        ),
        components=(
            _component("ema-crossover", "entry", fast=16, slow=64),
            _component("revenue-growth", "entry", threshold=0.05),
            _component("accrual-reversal", "entry", threshold=0.25),
            _component("ema-crossover", "exit", fast=16, slow=64),
            _component("accrual-reversal", "exit", threshold=0.25),
            _component("profitability-filter", "filter", min_roe=0.10),
            _component("leverage-filter", "filter", max_ratio=1.0),
        ),
        entry_logic="majority",
        exit_logic="any",
        combine_window_days=21,
        execution=ExecutionConfig(
            position_sizing="volatility_target",
            sizing_value=0.02,
            max_positions=10,
            max_position_pct=0.15,
            fill_timing="next_open",
            **_COSTS,
        ),
    )


_BUILDERS = {
    "rsi-mean-reversion": _rsi_mean_reversion,
    "macd-trend-following": _macd_trend_following,
    "donchian-breakout": _donchian_breakout,
    "dual-confirmation": _dual_confirmation,
    "regime-trend": _regime_trend,
    "regime-reversion": _regime_reversion,
    "macro-gated-trend": _macro_gated_trend,
    "quality-momentum": _quality_momentum,
    "test-candidate-systematic-1": _systematic_ewmac_long,
    "test-candidate-systematic-2": _systematic_ewmac_long_short,
    "test-candidate-systematic-3": _systematic_quality_value,
    "test-candidate-systematic-4": _systematic_cash_backed_growth,
}

#: Stable ids the frontend can offer as one-click starting points.
TEMPLATE_IDS: tuple[str, ...] = tuple(_BUILDERS)

#: The presets that replicate the AI-quant-book plan, shelved apart from the
#: generic starters so a user can tell a worked example from a research baseline.
BOOK_TEMPLATE_IDS: frozenset[str] = frozenset(
    {"regime-trend", "regime-reversion", "macro-gated-trend", "quality-momentum"}
)

SYSTEMATIC_TRADING_TEMPLATE_IDS: frozenset[str] = frozenset(
    {
        "test-candidate-systematic-1",
        "test-candidate-systematic-2",
        "test-candidate-systematic-3",
        "test-candidate-systematic-4",
    }
)


def template(template_id: str) -> StrategySpec:
    """Build one template. Built fresh each call so a caller that edits the
    returned spec cannot mutate the catalogue for everyone else."""
    try:
        return _BUILDERS[template_id]()
    except KeyError as exc:
        raise KeyError(
            f"unknown strategy template {template_id!r}; expected one of {TEMPLATE_IDS}"
        ) from exc


def catalogue() -> list[dict]:
    """Every template, as the API serves it."""
    out = []
    for template_id in TEMPLATE_IDS:
        spec = template(template_id)
        if template_id in BOOK_TEMPLATE_IDS:
            collection = "ai-quant-book"
        elif template_id in SYSTEMATIC_TRADING_TEMPLATE_IDS:
            collection = "systematic-trading"
        else:
            collection = "starter"
        out.append({"id": template_id, "collection": collection, **spec.to_dict()})
    return out
