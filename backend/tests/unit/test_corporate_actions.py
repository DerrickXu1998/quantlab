"""Splits and dividends: back-adjusted bars for signals, events for execution.

Every expected number is hand-computed here. The bars are GOOG-shaped: a
20-for-1 split takes a ~2,000 close to ~100 overnight with no real move, which
is exactly the case that used to read as a 95% crash.
"""

from __future__ import annotations

import pytest

from quantlab.execution import (
    CorporateAction,
    Decision,
    ExecutionConfig,
    ExecutionSimulator,
    adjustments,
    simulate,
)
from quantlab.research.runner import execution_config_for
from quantlab.synthetic.generator import Bar


def idealized_config(**kwargs):
    settings = {
        "fill_timing": "signal_close", "commission_bps": 0.0,
        "slippage_bps": 0.0, "max_volume_participation": None,
    }
    settings.update(kwargs)
    return ExecutionConfig(**settings)


def bars(closes, volume=1_000):
    """d000, d001, ... with high/low at +/-1% of the close."""
    return [
        Bar(
            date=f"d{i:03d}",
            open=float(c),
            high=float(c) * 1.01,
            low=float(c) * 0.99,
            close=float(c),
            volume=volume,
        )
        for i, c in enumerate(closes)
    ]


def split(ex_date, ratio):
    return CorporateAction(ex_date=ex_date, action_type="split", split_ratio=ratio)


def dividend(ex_date, amount):
    return CorporateAction(ex_date=ex_date, action_type="dividend", dividend=amount)


def buy(date="d000", direction="bullish"):
    return Decision(date=date, symbol="AAA", kind="entry", direction=direction)


# --- adjusted bars (what signals read) ------------------------------------


def test_split_divides_earlier_prices_and_multiplies_earlier_volume():
    raw = bars([2000.0, 2010.0, 100.0, 101.0])
    adjusted = adjustments.adjust(raw, [split("d002", 20.0)])
    assert [b.close for b in adjusted] == pytest.approx([100.0, 100.5, 100.0, 101.0])
    assert [b.volume for b in adjusted] == [20_000, 20_000, 1_000, 1_000]
    # The traded price survives for anything that needs it (market cap).
    assert [adjustments.raw_close(b) for b in adjusted] == [2000.0, 2010.0, 100.0, 101.0]


def test_dividend_scales_earlier_prices_by_the_payout_over_the_prior_close():
    raw = bars([100.0, 100.0, 99.0, 99.0])
    adjusted = adjustments.adjust(raw, [dividend("d002", 1.0)])
    # (100 - 1) / 100 = 0.99 before the ex-date, untouched from it on.
    assert [b.close for b in adjusted] == pytest.approx([99.0, 99.0, 99.0, 99.0])
    assert [b.volume for b in adjusted] == [1_000] * 4


def test_the_last_bar_always_keeps_its_traded_price():
    raw = bars([2000.0, 100.0, 100.0])
    adjusted = adjustments.adjust(raw, [split("d001", 20.0), dividend("d002", 0.5)])
    assert adjusted[-1].close == 100.0


def test_an_action_after_the_last_bar_is_not_in_force():
    """Point-in-time: a run ending before an ex-date is not adjusted for it."""
    raw = bars([100.0, 100.0, 100.0])
    assert adjustments.factors(raw, [split("d009", 2.0)]) == ([1.0] * 3, [1.0] * 3)
    rows = [
        {"symbol": "AAA", "ex_date": "d001", "action_type": "split", "split_ratio": 2.0},
        {"symbol": "AAA", "ex_date": "d009", "action_type": "split", "split_ratio": 3.0},
    ]
    kept = adjustments.by_symbol(rows, "split_dividend", end="d005")
    assert [a.ex_date for a in kept["AAA"]] == ["d001"]


def test_a_dividend_at_least_the_prior_close_is_skipped_not_applied():
    raw = bars([1.0, 1.0, 1.0])
    assert adjustments.factors(raw, [dividend("d001", 5.0)])[0] == [1.0] * 3


@pytest.mark.parametrize(
    ("mode", "kinds"),
    [("split_dividend", ["dividend", "split"]), ("split", ["split"]), ("none", [])],
)
def test_the_mode_decides_which_actions_apply(mode, kinds):
    rows = [
        {"symbol": "AAA", "ex_date": "d001", "action_type": "split", "split_ratio": 2.0},
        {"symbol": "AAA", "ex_date": "d001", "action_type": "dividend", "dividend": 0.5},
    ]
    kept = adjustments.by_symbol(rows, mode)
    assert sorted(a.action_type for a in kept.get("AAA", [])) == kinds


# --- execution (raw prices, actions as events) ----------------------------


def run(closes, actions, mode="split_dividend", decisions=None, **config):
    return simulate(
        ["AAA"],
        {"AAA": bars(closes)},
        decisions if decisions is not None else [buy()],
        idealized_config(price_adjustment=mode, **config),
        {"AAA": actions},
    )


def test_a_split_multiplies_shares_and_leaves_equity_unchanged():
    result = run([2000.0, 2000.0, 100.0, 100.0], [split("d002", 20.0)])
    trade = result.trades[0]
    assert trade.qty == pytest.approx(1000.0)  # 50 shares at 2,000 became 1,000
    assert trade.entry_price == pytest.approx(100.0)  # in today's share terms
    assert trade.return_pct == pytest.approx(0.0)
    assert result.equity[-1].value == pytest.approx(100_000.0)
    assert result.summary.splits_applied == 1


def test_without_adjustment_the_same_split_is_a_95_percent_loss():
    """The behaviour this replaces, kept under price_adjustment="none"."""
    result = run([2000.0, 2000.0, 100.0, 100.0], [split("d002", 20.0)], mode="none")
    assert result.trades[0].return_pct == pytest.approx(-0.95)
    assert result.equity[-1].value == pytest.approx(5_000.0)


def test_a_long_is_paid_the_dividend_in_cash_on_the_ex_date():
    result = run([100.0, 100.0, 99.0, 99.0], [dividend("d002", 1.0)])
    trade = result.trades[0]
    # 1,000 shares: the 1,000 lost to the ex-date drop comes back as cash.
    assert trade.dividends == pytest.approx(1_000.0)
    assert trade.pnl == pytest.approx(0.0)
    assert trade.return_pct == pytest.approx(0.0)
    assert result.equity[-1].value == pytest.approx(100_000.0)
    assert result.summary.total_dividends == pytest.approx(1_000.0)


def test_split_only_ignores_dividends():
    result = run([100.0, 100.0, 99.0, 99.0], [dividend("d002", 1.0)], mode="split")
    assert result.trades[0].dividends == 0.0
    assert result.equity[-1].value == pytest.approx(99_000.0)


def test_a_position_opened_on_the_ex_date_is_not_paid():
    result = run([100.0, 100.0, 99.0, 99.0], [dividend("d002", 1.0)], decisions=[buy("d002")])
    assert result.trades[0].dividends == 0.0
    assert result.summary.dividends_applied == 0


def test_a_short_pays_the_dividend():
    result = run(
        [100.0, 100.0, 99.0, 99.0],
        [dividend("d002", 1.0)],
        decisions=[buy(direction="bearish")],
        allow_shorts=True,
    )
    trade = result.trades[0]
    assert trade.side == "short"
    assert trade.dividends == pytest.approx(-1_000.0)
    # +1,000 from the price drop, -1,000 paid to the lender.
    assert trade.pnl == pytest.approx(0.0)
    assert result.equity[-1].value == pytest.approx(100_000.0)


def test_a_stop_moves_with_the_split_instead_of_firing_on_it():
    closes = [2000.0, 2000.0, 100.0, 100.0]
    adjusted = run(closes, [split("d002", 20.0)], stop_loss_pct=0.05)
    assert adjusted.trades[0].open  # stop 1,900 became 95; the low is 99
    raw = run(closes, [split("d002", 20.0)], mode="none", stop_loss_pct=0.05)
    assert raw.trades[0].exit_reason == "stop_loss"


def test_an_atr_stop_is_not_widened_by_the_split():
    """ATR on raw prices would count the 1,900 overnight drop as range."""
    closes = [2000.0] * 20 + [100.0] * 20
    entry = [Decision(date="d025", symbol="AAA", kind="entry", direction="bullish")]

    def stop(mode):
        simulator = ExecutionSimulator(
            ["AAA"],
            {"AAA": bars(closes)},
            idealized_config(price_adjustment=mode, atr_stop_multiple=2.0),
            {"AAA": [split("d020", 20.0)]},
        )
        for _ in simulator.iter_days(entry):
            pass
        return simulator.open_positions()[0].stop_price

    # Adjusted ATR is the 2.0 high-low range of a 100 close: stop at 96.
    assert stop("split") == pytest.approx(96.0)
    # Raw, the split day's 1,900 "range" is still in the average: no real stop.
    assert stop("none") < 0


# --- stored runs ----------------------------------------------------------


def test_a_run_stored_before_the_setting_existed_reexecutes_unadjusted():
    assert execution_config_for({}).price_adjustment == "none"
    assert execution_config_for({"execution": {"fill_timing": "next_open"}}).price_adjustment == (
        "none"
    )
    stored = {"execution": {"price_adjustment": "split"}}
    assert execution_config_for(stored).price_adjustment == "split"


def test_a_run_stored_before_volume_capacity_reexecutes_with_unlimited_liquidity():
    """Its stored result had no capacity limit; filling the gap with today's
    1% default made its replay disagree with the result it shows."""
    pre_capacity = {k: v for k, v in idealized_config().to_dict().items()
                    if k not in ("max_volume_participation", "order_expiry_days")}
    assert execution_config_for({"execution": pre_capacity}).max_volume_participation is None
    # Stored explicitly, by a build that had the setting: kept as stored.
    capped = {**idealized_config().to_dict(), "max_volume_participation": 0.05}
    assert execution_config_for({"execution": capped}).max_volume_participation == 0.05


def test_a_run_stored_before_execution_criteria_reexecutes_as_it_ran():
    config = execution_config_for({})
    assert config.fill_timing == "signal_close"
    assert config.commission_bps == 0.0
    assert config.slippage_bps == 0.0
    assert config.max_volume_participation is None


def test_new_configs_default_to_split_and_dividend_adjustment():
    assert idealized_config().price_adjustment == "split_dividend"
    with pytest.raises(ValueError, match="price_adjustment"):
        idealized_config(price_adjustment="total")


# --- studies (lines drawn over candles) -------------------------------------


def test_studies_restated_in_traded_terms_sit_on_raw_candles():
    """A flat 2,000 -> 100 series across a 20:1 split: the SMA is 100 adjusted
    everywhere, and 2,000 before the split / 100 after in traded terms."""
    from quantlab.research.studies import compute_studies

    run = {"id": "r", "model_name": "sma-crossover", "parameters": {"fast": 2, "slow": 3}}
    raw = bars([2000.0] * 5 + [100.0] * 5)
    actions = [split("d005", 20.0)]
    adjusted = adjustments.adjust(raw, actions)

    def line(price_factors):
        result = compute_studies(run=run, symbol="AAA", bars=adjusted, price_factors=price_factors)
        fast = next(s for s in result.studies if s.key.endswith("sma_fast"))
        return {p.date: p.value for p in fast.points}

    on_signal_basis = line(None)
    traded = line(adjustments.factors(raw, actions)[0])
    assert on_signal_basis["d003"] == pytest.approx(100.0)
    assert traded["d003"] == pytest.approx(2000.0)
    assert traded["d008"] == pytest.approx(100.0) == on_signal_basis["d008"]


# --- a split and a dividend on the same ex-date --------------------------------
#
# 100 shares at 100. On d002 a 2:1 split and a $1 dividend (per post-split
# share, as dividends are quoted on their ex-date) go ex together; the stock
# closes at 49. The holder has 200 shares x 49 = 9,800 plus 200 x $1 = 200 in
# cash: exactly the 10,000 they started with. The input order of the two rows
# must not matter, and the loader used to sort "dividend" before "split".

SAME_DAY = [split("d002", 2.0), dividend("d002", 1.0)]
SAME_DAY_CLOSES = [100.0, 100.0, 49.0, 49.0]


def _same_day(actions, direction="bullish", **config):
    return run(
        SAME_DAY_CLOSES, actions, decisions=[buy(direction=direction)],
        initial_capital=10_000.0, allow_shorts=True, **config,
    )


@pytest.mark.parametrize("actions", [SAME_DAY, SAME_DAY[::-1]], ids=["split-first", "div-first"])
def test_a_same_day_split_and_dividend_leave_a_long_whole(actions):
    result = _same_day(actions)
    trade = result.trades[0]
    assert trade.qty == pytest.approx(200.0)
    assert trade.dividends == pytest.approx(200.0)
    assert result.summary.total_dividends == pytest.approx(200.0)
    assert trade.pnl == pytest.approx(0.0)
    assert trade.return_pct == pytest.approx(0.0)
    assert result.equity[-1].value == pytest.approx(10_000.0)


@pytest.mark.parametrize("actions", [SAME_DAY, SAME_DAY[::-1]], ids=["split-first", "div-first"])
def test_a_same_day_split_and_dividend_leave_a_short_whole(actions):
    result = _same_day(actions, direction="bearish")
    trade = result.trades[0]
    assert trade.side == "short"
    assert trade.qty == pytest.approx(200.0)
    assert trade.dividends == pytest.approx(-200.0)
    assert trade.pnl == pytest.approx(0.0)
    assert result.equity[-1].value == pytest.approx(10_000.0)


def test_the_loader_orders_a_split_before_a_same_day_dividend():
    rows = [
        {"symbol": "AAA", "ex_date": "d002", "action_type": "dividend", "dividend": 1.0},
        {"symbol": "AAA", "ex_date": "d002", "action_type": "split", "split_ratio": 2.0},
    ]
    for ordered in (rows, rows[::-1]):
        loaded = adjustments.by_symbol(ordered, "split_dividend")["AAA"]
        assert [a.action_type for a in loaded] == ["split", "dividend"]
        assert _same_day(loaded).equity[-1].value == pytest.approx(10_000.0)


@pytest.mark.parametrize("actions", [SAME_DAY, SAME_DAY[::-1]], ids=["split-first", "div-first"])
def test_back_adjustment_compares_a_same_day_dividend_in_pre_split_terms(actions):
    """Pre-ex factor = 1/2 for the split x (100 - 1 x 2) / 100 for the dividend:
    the $1 is per new share, $2 per share of the 100 close. The adjusted series
    is flat across the ex-date, as the holder's wealth is."""
    raw = bars(SAME_DAY_CLOSES)
    price, volume = adjustments.factors(raw, actions)
    assert price == pytest.approx([0.49, 0.49, 1.0, 1.0])
    assert volume == pytest.approx([2.0, 2.0, 1.0, 1.0])
    closes = [bar.close for bar in adjustments.adjust(raw, actions)]
    assert closes == pytest.approx([49.0, 49.0, 49.0, 49.0])


def test_back_adjustment_multiplies_several_same_day_splits():
    actions = [dividend("d002", 1.0), split("d002", 2.0), split("d002", 1.5)]
    price, _ = adjustments.factors(bars([90.0, 90.0, 29.0, 29.0]), actions)
    # Ratio 3: $1 per new share is $3 on the 90 close; (90 - 3) / 90 / 3.
    assert price[0] == pytest.approx(87.0 / 90.0 / 3.0)


@pytest.mark.parametrize("actions", [SAME_DAY, SAME_DAY[::-1]], ids=["split-first", "div-first"])
def test_columnar_bars_agree_with_row_wise_on_a_same_day_split_and_dividend(actions):
    import numpy as np

    from quantlab.execution.bars import BarSeries

    raw = bars(SAME_DAY_CLOSES)
    stamps = np.array([f"2024-01-0{i + 1}" for i in range(4)], dtype="datetime64[D]")
    columns = BarSeries(
        stamps, [b.open for b in raw], [b.high for b in raw], [b.low for b in raw],
        [b.close for b in raw], [b.volume for b in raw],
    )
    dated = [
        CorporateAction(f"2024-01-0{int(a.ex_date[1:]) + 1}", a.action_type,
                        a.split_ratio, a.dividend)
        for a in actions
    ]
    price, _ = adjustments.factors(columns, dated)
    assert list(price) == pytest.approx([0.49, 0.49, 1.0, 1.0])

    result = simulate(
        ["AAA"], {"AAA": columns},
        [Decision(date="2024-01-01", symbol="AAA", kind="entry", direction="bullish")],
        idealized_config(initial_capital=10_000.0), {"AAA": dated},
    )
    assert result.trades[0].qty == pytest.approx(200.0)
    assert result.trades[0].dividends == pytest.approx(200.0)
    assert result.equity[-1].value == pytest.approx(10_000.0)


@pytest.mark.parametrize("actions", [SAME_DAY, SAME_DAY[::-1]], ids=["split-first", "div-first"])
def test_the_benchmark_is_whole_across_a_same_day_split_and_dividend(actions):
    from quantlab.research import performance

    raw = [
        Bar(date=f"2024-01-0{i + 1}", open=c, high=c, low=c, close=c, volume=1_000)
        for i, c in enumerate(SAME_DAY_CLOSES)
    ]
    dated = [
        CorporateAction("2024-01-03", a.action_type, a.split_ratio, a.dividend)
        for a in actions
    ]
    result = performance.compute_performance(
        run_id="same-day",
        signals=[{"symbol": "AAA", "date": "2024-01-01", "direction": "bullish",
                  "trigger_values": {}, "data_window_end": "2024-01-01"}],
        bars_by_symbol={"AAA": raw},
        symbols=["AAA"],
        execution=idealized_config(initial_capital=10_000.0),
        corporate_actions={"AAA": dated},
    )
    assert result.benchmark[-1].value == pytest.approx(10_000.0)
    assert result.equity[-1].value == pytest.approx(10_000.0)
    assert result.trades[0].pnl == pytest.approx(0.0)


def test_a_partly_unreadable_config_keeps_the_settings_it_can_read():
    """A newer build's key, or a value newer validation rejects, must not turn
    a run that paid costs into a cost-free one at the signal close."""
    stored = {
        "fill_timing": "next_open",
        "commission_bps": 7.0,
        "slippage_bps": 3.0,
        "price_adjustment": "split",
        "a_setting_from_a_newer_build": True,
        "max_volume_participation": -5,  # invalid here
    }
    config = execution_config_for({"execution": stored})
    assert config.fill_timing == "next_open"
    assert config.commission_bps == 7.0
    assert config.slippage_bps == 3.0
    assert config.price_adjustment == "split"
    # The unreadable value falls back to what a run without it meant.
    assert config.max_volume_participation is None


def test_an_unreadable_config_keeps_settings_that_depend_on_each_other():
    """volatility_target sizing is valid only beside its sizing_value; taken
    one at a time in stored order, it would be dropped for equal weight."""
    stored = {
        "position_sizing": "volatility_target",
        "sizing_value": 0.15,
        "commission_bps": 4.0,
        "a_setting_from_a_newer_build": 1,
    }
    config = execution_config_for({"execution": stored})
    assert config.position_sizing == "volatility_target"
    assert config.sizing_value == 0.15
    assert config.commission_bps == 4.0


#: Every ExecutionConfig setting, as of the last time someone decided what a
#: stored run *without* it meant. A run's stored config is the full to_dict of
#: the build that ran it, so a key it lacks is a setting added since -- and if
#: that setting's default changes behaviour, an old run rebuilt or backfilled
#: would silently run under it (as max_volume_participation once did).
_DECIDED = {
    "initial_capital", "position_sizing", "sizing_value", "max_positions",
    "max_position_pct", "fill_timing", "commission_bps", "slippage_bps",
    "stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "atr_stop_multiple",
    "atr_period", "max_holding_days", "allow_shorts", "borrow_cost_bps",
    "price_adjustment", "intraday_resolution", "bar_frequency",
    "max_volume_participation", "order_expiry_days", "min_holding_days", "cooldown_days",
    # Allocation sizing: each defaults to None (off), which is how every run
    # before it executed, so a stored config without them needs no legacy value.
    "target_exposure", "min_allocation_score", "rebalance_frequency",
    "rebalance_threshold", "max_turnover",
}


def test_a_new_execution_setting_must_say_what_its_absence_meant():
    from quantlab.execution import ExecutionConfig

    added = set(ExecutionConfig.__dataclass_fields__) - _DECIDED
    assert not added, (
        f"new execution setting(s) {sorted(added)}: if the default changes how a run "
        "executes, add what a run stored before it meant to runner._LEGACY_EXECUTION; "
        "then add the name to _DECIDED here"
    )


def test_a_weekend_split_and_a_monday_dividend_share_a_bar_and_its_share_terms():
    """No bar on d002 (a Saturday): the split takes effect on d003's bar, as
    the dividend does, split first -- so the dividend is per post-split share
    there too, though the two ex-date strings differ."""
    from dataclasses import replace as dc_replace

    raw = [dc_replace(b, date=d) for b, d in zip(
        bars(SAME_DAY_CLOSES), ["d000", "d001", "d003", "d004"], strict=True
    )]
    actions = [split("d002", 2.0), dividend("d003", 1.0)]
    price, _ = adjustments.factors(raw, actions)
    assert price == pytest.approx([0.49, 0.49, 1.0, 1.0])
