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
        ExecutionConfig(price_adjustment=mode, **config),
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
            ExecutionConfig(price_adjustment=mode, atr_stop_multiple=2.0),
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


def test_new_configs_default_to_split_and_dividend_adjustment():
    assert ExecutionConfig().price_adjustment == "split_dividend"
    with pytest.raises(ValueError, match="price_adjustment"):
        ExecutionConfig(price_adjustment="total")
