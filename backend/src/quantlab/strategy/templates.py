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


_BUILDERS = {
    "rsi-mean-reversion": _rsi_mean_reversion,
    "macd-trend-following": _macd_trend_following,
    "donchian-breakout": _donchian_breakout,
    "dual-confirmation": _dual_confirmation,
}

#: Stable ids the frontend can offer as one-click starting points.
TEMPLATE_IDS: tuple[str, ...] = tuple(_BUILDERS)


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
        out.append({"id": template_id, **spec.to_dict()})
    return out
