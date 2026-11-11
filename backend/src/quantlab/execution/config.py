"""Execution criteria: what turns a signal into a trade.

Before this module those criteria existed, but only as prose in
``performance.ASSUMPTIONS`` and as hardcoded behaviour in two places that had to
be kept in step by hand. Every one of them is now a field a user can set, and
:meth:`ExecutionConfig.assumptions` regenerates that prose *from the values that
actually ran* -- so a result can no longer claim "no transaction costs are
charged" while a run charged them.

Validation raises :class:`ValueError` naming the offending field. The API layer
turns that into a 422; the library stays HTTP-agnostic (Constitution I).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from quantlab.execution.adjustments import PRICE_ADJUSTMENT
from quantlab.execution.bars import (
    BAR_FREQUENCIES,
    BARS_PER_SESSION,
    SESSIONS_PER_YEAR,
    is_intraday,
)

#: Notional book size when the caller does not set one. Arbitrary but fixed:
#: every ratio the performance module reports is scale-invariant, so this only
#: sets the axis labels.
INITIAL_CAPITAL = 100_000.0

POSITION_SIZING: tuple[str, ...] = (
    "equal_weight",
    "fixed_fraction",
    "fixed_notional",
    "volatility_target",
    "equal_active",
    "signal_strength",
    "signal_inverse_volatility",
)

#: Sizing modes that share one pool of capital and keep target weights across
#: every held position, rather than sizing each position once at entry. A new
#: signal, a changed score or an exit elsewhere can resize positions the
#: strategy did not signal on.
ALLOCATION_SIZING: tuple[str, ...] = (
    "equal_active",
    "signal_strength",
    "signal_inverse_volatility",
)

#: When allocation targets are recomputed and traded toward. ``on_signal``: on
#: a session whose signals change the allocation. ``daily`` / ``weekly`` /
#: ``monthly``: every session, the first session of each ISO week, the first
#: session of each calendar month.
REBALANCE_FREQUENCY: tuple[str, ...] = ("on_signal", "daily", "weekly", "monthly")

#: The settings only allocation sizing reads. Each defaults to ``None`` so a
#: legacy config is unchanged, and serialises without them (``to_dict``).
_ALLOCATION_FIELDS: tuple[str, ...] = (
    "target_exposure",
    "min_allocation_score",
    "rebalance_frequency",
    "rebalance_threshold",
    "max_turnover",
)

FILL_TIMING: tuple[str, ...] = (
    "signal_close",
    "next_open",
    "next_close",
    "next_typical",
    "next_vwap",
)

#: Fill timings that queue the order for the session after the signal. The
#: rest of the engine asks this rather than comparing names.
DEFERRED_FILL_TIMING: tuple[str, ...] = ("next_open", "next_close", "next_typical", "next_vwap")

#: How finely execution looks inside a session. ``daily``: every fill and
#: protective exit is decided from the daily bar alone. ``minute``: the
#: session's minute bars decide which protective level was touched first and
#: when, and supply a real VWAP. Signals are daily either way.
INTRADAY_RESOLUTION: tuple[str, ...] = ("daily", "minute")

#: Why a position was closed. Recorded per trade, because "the strategy said so"
#: and "the stop caught it" are different facts about a strategy and averaging
#: them into one win rate hides which one is doing the work.
EXIT_REASONS: tuple[str, ...] = (
    "signal",
    "stop_loss",
    "take_profit",
    "trailing_stop",
    "max_holding",
    "end_of_window",
    "rebalance",
)

#: One basis point as a fraction.
BPS = 1e-4

#: Trading days per year, for annualising a realised volatility estimate.
TRADING_DAYS_PER_YEAR = 252


def _positive(name: str, value: float | None, *, allow_zero: bool = False) -> None:
    if value is None:
        return
    if allow_zero and value < 0:
        raise ValueError(f"{name} must be >= 0")
    if not allow_zero and value <= 0:
        raise ValueError(f"{name} must be > 0")


def _fraction(name: str, value: float | None) -> None:
    """A percentage expressed as a fraction: 0.05 is five percent.

    The upper bound is not pedantry. A user who types ``5`` meaning "five
    percent" would otherwise get a stop 500% away from entry, which never
    triggers, and the backtest would look like the stop simply never helped.
    """
    if value is None:
        return
    if not 0 < value <= 1:
        raise ValueError(f"{name} must be a fraction in (0, 1] -- 0.05 means 5%")


@dataclass(frozen=True)
class AllocationSettings:
    """The allocation settings with their defaults resolved.

    ``target_exposure`` is gross (longs plus shorts) as a fraction of equity;
    ``min_score`` the lowest signal score that is allocated; ``frequency`` one
    of :data:`REBALANCE_FREQUENCY`; ``threshold`` the smallest weight change
    that is traded; ``max_turnover`` the most total weight change one
    rebalance may trade, or ``None`` for no cap.
    """

    target_exposure: float
    min_score: float
    frequency: str
    threshold: float
    max_turnover: float | None


@dataclass(frozen=True)
class ExecutionConfig:
    """How signals become fills. Every field is user-settable."""

    initial_capital: float = INITIAL_CAPITAL

    # --- sizing ---
    position_sizing: str = "equal_weight"
    #: Read only by some modes: the fraction of equity (fixed_fraction), the
    #: cash notional per trade (fixed_notional), or the target annualised
    #: volatility (volatility_target). Ignored by equal_weight.
    sizing_value: float | None = None
    max_positions: int | None = None
    max_position_pct: float = 1.0

    # --- portfolio allocation (ALLOCATION_SIZING only; None = the default) ---
    #: Gross exposure targeted across all positions, a fraction in (0, 1].
    #: Default 1.0.
    target_exposure: float | None = None
    #: Signals scoring below this, in [0, 1], get no allocation. Default 0.
    min_allocation_score: float | None = None
    #: One of REBALANCE_FREQUENCY. Default ``on_signal``.
    rebalance_frequency: str | None = None
    #: Weight changes smaller than this, in [0, 1), are not traded. Default 0.
    rebalance_threshold: float | None = None
    #: Most total absolute weight change one rebalance trades, in (0, 2].
    #: Default: no cap.
    max_turnover: float | None = None

    # --- timing and costs ---
    fill_timing: str = "next_open"
    commission_bps: float = 1.0
    slippage_bps: float = 5.0

    # --- liquidity ---
    max_volume_participation: float | None = 0.01
    order_expiry_days: int = 5

    # --- risk controls ---
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None
    atr_stop_multiple: float | None = None
    atr_period: int = 14

    # --- holding period ---
    max_holding_days: int | None = None
    min_holding_days: int = 0
    cooldown_days: int = 0

    allow_shorts: bool = False
    #: Annualised cost of borrowing stock to short, in basis points of the
    #: short's market value, accrued each session the short is held (/252).
    #: Liquid large caps borrow for 25-50 bps a year; hard-to-borrow names can
    #: cost hundreds. Zero -- the default -- means shorting is free, which is
    #: exactly what the assumptions list says when it is left there.
    borrow_cost_bps: float = 0.0

    # --- corporate actions ---
    #: How splits and dividends are treated (``execution.adjustments``).
    #: ``split_dividend``: signals read back-adjusted prices; execution trades
    #: raw prices, a split multiplies the shares held and a dividend is paid
    #: to a long and charged to a short in cash on its ex-date. ``split``: the
    #: same for splits only, so returns are price-only. ``none``: raw prices
    #: everywhere and no events -- the behaviour before this setting existed,
    #: and what a stored run without it re-executes under.
    price_adjustment: str = "split_dividend"

    # --- intraday accuracy ---
    #: ``daily`` (default) or ``minute``: see INTRADAY_RESOLUTION. Opens and
    #: closes are auction prices and come from the daily bar in both modes;
    #: minute bars only decide what happens between them.
    intraday_resolution: str = "daily"

    # --- signal bars ---
    #: The bars signals are computed on and the engine steps through: ``1d``
    #: (default) or intraday ``1h`` / ``15m`` / ``5m``, built from the IEX
    #: minute bars. Intraday, holding periods and cooldown count trading sessions;
    #: ATR and volatility lookbacks count bars, and annualisation is per bar.
    bar_frequency: str = "1d"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if self.position_sizing not in POSITION_SIZING:
            raise ValueError(
                f"position_sizing must be one of {POSITION_SIZING}, got {self.position_sizing!r}"
            )
        if self.price_adjustment not in PRICE_ADJUSTMENT:
            raise ValueError(
                f"price_adjustment must be one of {PRICE_ADJUSTMENT}, got {self.price_adjustment!r}"
            )
        if self.fill_timing not in FILL_TIMING:
            raise ValueError(
                f"fill_timing must be one of {FILL_TIMING}, got {self.fill_timing!r}"
            )
        if self.bar_frequency not in BAR_FREQUENCIES:
            raise ValueError(
                f"bar_frequency must be one of {BAR_FREQUENCIES}, got {self.bar_frequency!r}"
            )
        if is_intraday(self.bar_frequency) and self.intraday_resolution != "daily":
            # Minute accuracy refines a daily bar; an intraday bar is already
            # the unit execution steps through.
            raise ValueError("intraday_resolution minute applies to bar_frequency 1d only")
        if self.intraday_resolution not in INTRADAY_RESOLUTION:
            raise ValueError(
                f"intraday_resolution must be one of {INTRADAY_RESOLUTION}, "
                f"got {self.intraday_resolution!r}"
            )
        # A VWAP needs the session's volume profile, which only minute bars
        # have. Quietly substituting the typical price would be a different
        # fill from the one the form asked for.
        if self.fill_timing == "next_vwap" and self.intraday_resolution != "minute":
            raise ValueError("fill_timing next_vwap needs intraday_resolution minute")

        # Modes that need a value must have one; equal_weight must not, because
        # silently ignoring a number the user typed is how a run quietly does
        # something other than what the form said.
        if self.position_sizing == "equal_weight" or self.position_sizing in ALLOCATION_SIZING:
            if self.sizing_value is not None:
                raise ValueError(
                    f"sizing_value is not used by {self.position_sizing} sizing; leave it unset"
                )
        elif self.sizing_value is None:
            raise ValueError(f"sizing_value is required for {self.position_sizing} sizing")

        if self.position_sizing == "fixed_fraction":
            _fraction("sizing_value", self.sizing_value)
        elif self.position_sizing in ("fixed_notional", "volatility_target"):
            _positive("sizing_value", self.sizing_value)

        if self.max_positions is not None and self.max_positions < 1:
            raise ValueError("max_positions must be >= 1 when set")
        if not 0 < self.max_position_pct <= 1:
            raise ValueError("max_position_pct must be a fraction in (0, 1]")
        self._validate_allocation()

        _positive("commission_bps", self.commission_bps, allow_zero=True)
        _positive("slippage_bps", self.slippage_bps, allow_zero=True)
        _fraction("max_volume_participation", self.max_volume_participation)
        if self.order_expiry_days < 1:
            raise ValueError("order_expiry_days must be >= 1")
        _positive("borrow_cost_bps", self.borrow_cost_bps, allow_zero=True)
        if self.borrow_cost_bps > 5_000:
            # 50%/yr. Anything above is almost certainly a percent typed as bps.
            raise ValueError("borrow_cost_bps is annual basis points; 50 means 0.5% a year")

        _fraction("stop_loss_pct", self.stop_loss_pct)
        _fraction("take_profit_pct", self.take_profit_pct)
        _fraction("trailing_stop_pct", self.trailing_stop_pct)
        _positive("atr_stop_multiple", self.atr_stop_multiple)
        if self.atr_period < 2:
            raise ValueError("atr_period must be >= 2")

        if self.max_holding_days is not None and self.max_holding_days < 1:
            raise ValueError("max_holding_days must be >= 1 when set")
        if self.min_holding_days < 0:
            raise ValueError("min_holding_days must be >= 0")
        if self.cooldown_days < 0:
            raise ValueError("cooldown_days must be >= 0")
        if (
            self.max_holding_days is not None
            and self.min_holding_days > self.max_holding_days
        ):
            raise ValueError("min_holding_days must be <= max_holding_days")

    def _validate_allocation(self) -> None:
        if self.position_sizing not in ALLOCATION_SIZING:
            # Same stance as sizing_value under equal_weight: a number the
            # user typed must not be silently ignored.
            for name in _ALLOCATION_FIELDS:
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"{name} is only used by portfolio allocation sizing "
                        f"({', '.join(ALLOCATION_SIZING)}); leave it unset"
                    )
            return
        _fraction("target_exposure", self.target_exposure)
        score = self.min_allocation_score
        if score is not None and not 0 <= score <= 1:
            raise ValueError("min_allocation_score must be in [0, 1]")
        if (
            self.rebalance_frequency is not None
            and self.rebalance_frequency not in REBALANCE_FREQUENCY
        ):
            raise ValueError(
                f"rebalance_frequency must be one of {REBALANCE_FREQUENCY}, "
                f"got {self.rebalance_frequency!r}"
            )
        threshold = self.rebalance_threshold
        if threshold is not None and not 0 <= threshold < 1:
            raise ValueError(
                "rebalance_threshold must be a fraction in [0, 1) -- 0.02 means 2% of equity"
            )
        turnover = self.max_turnover
        if turnover is not None and not 0 < turnover <= 2:
            # 2 is a full reversal of a fully invested book: everything sold
            # and as much bought again.
            raise ValueError(
                "max_turnover must be a fraction in (0, 2] -- 0.5 means 50% of equity"
            )

    def allocation(self) -> AllocationSettings | None:
        """The allocation settings with defaults resolved; ``None`` for legacy sizing."""
        if self.position_sizing not in ALLOCATION_SIZING:
            return None
        return AllocationSettings(
            target_exposure=1.0 if self.target_exposure is None else self.target_exposure,
            min_score=0.0 if self.min_allocation_score is None else self.min_allocation_score,
            frequency=self.rebalance_frequency or "on_signal",
            threshold=0.0 if self.rebalance_threshold is None else self.rebalance_threshold,
            max_turnover=self.max_turnover,
        )

    # -- time units --------------------------------------------------------

    @property
    def bars_per_session(self) -> int:
        return BARS_PER_SESSION[self.bar_frequency]

    @property
    def periods_per_year(self) -> int:
        """Bars a year, for annualising volatility and accruing borrow."""
        return SESSIONS_PER_YEAR * self.bars_per_session

    # -- warm-up -----------------------------------------------------------

    @property
    def extra_lookback_days(self) -> int:
        """Bars of history the *execution* layer needs on top of the strategy's.

        An ATR stop is set from the ATR as at the entry bar, so a position
        opened on the first bar of the window still needs ``atr_period`` bars
        behind it or its stop would be undefined. Inverse-volatility
        allocation reads the trailing volatility of ``atr_period`` returns,
        which needs the same ``atr_period + 1`` closes. (``volatility_target``
        reads that volatility too but has never added warm-up; changing that
        would move every stored run's window, so it is left alone.)
        """
        if (
            self.atr_stop_multiple is not None
            or self.position_sizing == "signal_inverse_volatility"
        ):
            return self.atr_period + 1
        return 0

    # -- disclosure --------------------------------------------------------

    def assumptions(self) -> list[str]:
        """The caveats that actually apply to a run under this config.

        Generated rather than fixed, so the list travels with the numbers and
        cannot drift from them (the same stance the corporate-action warning
        takes).
        """
        out: list[str] = []

        if self.allow_shorts:
            borrow = (
                f"Shorts pay {self.borrow_cost_bps:g} bps a year of borrow on their market "
                "value, accrued each session held; locate availability and short-sale "
                "restrictions are not modelled."
                if self.borrow_cost_bps
                else "Borrow costs, locate availability and short-sale restrictions are not "
                "modelled -- shorting is free here, which it is not in practice."
            )
            out.append(
                "Long and short: a bearish entry opens a short and a bullish signal covers it. "
                + borrow
            )
        else:
            out.append("Long-only: a bearish signal closes a position, it never opens a short.")

        if self.position_sizing == "equal_weight":
            out.append(
                "Equal-weight: capital is split evenly across the instruments selected for the "
                "run, each sleeve trades only its own instrument, and an untraded sleeve sits "
                "in cash."
            )
        elif self.position_sizing == "fixed_fraction":
            out.append(
                f"Fixed-fraction sizing: each position is opened at {self.sizing_value:.1%} of "
                "book equity at the moment of entry, from a shared cash pool."
            )
        elif self.position_sizing == "fixed_notional":
            out.append(
                f"Fixed-notional sizing: each position is opened at {self.sizing_value:,.2f} of "
                "cash regardless of book size, from a shared cash pool."
            )
        elif self.position_sizing == "volatility_target":
            out.append(
                f"Volatility-targeted sizing: each position is scaled so its own realised "
                f"volatility contributes about {self.sizing_value:.1%} annualised, capped at "
                f"{self.max_position_pct:.0%} of equity."
            )

        allocation = self.allocation()
        if allocation is not None:
            out.extend(self._allocation_assumptions(allocation))
        else:
            if self.max_positions is not None:
                out.append(
                    f"At most {self.max_positions} positions are held at once; a signal "
                    "arriving when the book is full is dropped, not queued."
                )
            if self.max_position_pct < 1.0 and self.position_sizing != "equal_weight":
                out.append(f"No single position exceeds {self.max_position_pct:.0%} of equity.")

        if self.fill_timing == "signal_close":
            out.append("Signal entries and exits are marked at the close of the signal date.")
        else:
            where = {
                "next_open": "the open of the session after the signal date",
                "next_close": "the close of the session after the signal date",
                "next_typical": (
                    "the typical price, (high + low + close) / 3, of the session after the "
                    "signal date -- a stand-in for VWAP, since daily bars carry no intraday "
                    "volume profile"
                ),
                "next_vwap": (
                    "the volume-weighted average price of the session after the signal "
                    "date, from its minute bars -- an order worked through the whole "
                    "session. Volume is the IEX feed's, which weights the minutes but is "
                    "a small share of all trading; a session without minute bars falls back "
                    "to the typical price"
                ),
            }[self.fill_timing]
            out.append(
                f"Signal entries and exits are filled at {where}; a signal on the last bar "
                "of the window has no session to fill in and is dropped."
            )

        if self.commission_bps or self.slippage_bps:
            parts = []
            if self.commission_bps:
                parts.append(f"{self.commission_bps:g} bps commission")
            if self.slippage_bps:
                parts.append(f"{self.slippage_bps:g} bps slippage")
            out.append(
                f"Costs charged on both sides of every trade: {' and '.join(parts)}. "
                "Market impact, spread beyond that slippage, and financing are not modelled."
            )
        else:
            out.append("No transaction costs and no slippage are charged.")

        if self.max_volume_participation is not None:
            out.append(
                f"Each order fills at most {self.max_volume_participation:.1%} of a bar's "
                f"volume. Unfilled signal quantity carries for up to {self.order_expiry_days} "
                "trading sessions; protective-exit quantity remains active until filled or the "
                "window ends. Zero-volume bars cannot fill. Intraday capacity uses IEX volume, "
                "a conservative proxy rather than consolidated market volume."
            )

        risk: list[str] = []
        if self.stop_loss_pct is not None:
            risk.append(f"a {self.stop_loss_pct:.1%} stop from entry")
        if self.atr_stop_multiple is not None:
            risk.append(
                f"an ATR({self.atr_period}) stop at {self.atr_stop_multiple:g}x the range as at "
                "entry"
            )
        if self.trailing_stop_pct is not None:
            risk.append(f"a {self.trailing_stop_pct:.1%} trailing stop from the best close held")
        if self.take_profit_pct is not None:
            risk.append(f"a {self.take_profit_pct:.1%} profit target")
        if risk:
            out.append(
                "Protective exits: " + ", ".join(risk) + ". They are tested against each bar's "
                "own high and low, before any signal exit. When a stop and a target both sit "
                "inside one bar's range the stop is taken, because a daily bar cannot say which "
                "came first and assuming the better one flatters the result."
            )
            if self.stop_loss_pct is not None or self.atr_stop_multiple is not None:
                out.append(
                    "A stop the session gapped straight through fills at that session's "
                    "open, which is worse than the stop itself."
                )
            if self.take_profit_pct is not None:
                out.append(
                    "A profit target the session gapped straight through still fills at "
                    "the target, not at the better opening price: collecting every "
                    "favourable gap would add up to an edge no live book earns."
                )

        if self.intraday_resolution == "minute" and risk:
            out.append(
                "Protective exits are resolved on minute bars: when a session's range "
                "touches a level, its minutes decide which level was crossed first and "
                "when, so a target reached before the stop is taken. Within one minute "
                "the stop still wins. A gap through a level at the open fills at the "
                "official open. A session with no minute bars (before 2016-12-12, or a "
                "day the feed missed), or whose minutes never reach the level the daily "
                "range shows, falls back to the daily rule; the summary counts them as "
                "minute_fallbacks."
            )

        if is_intraday(self.bar_frequency):
            out.append(
                f"Signals and fills are on {self.bar_frequency} bars built from the IEX minute "
                "feed, regular hours only; a bar's open and close are that feed's, not the "
                "official auction prices. Holding periods and cooldown count trading sessions; "
                "ATR and volatility lookbacks count bars. Fundamentals and macro series are read "
                "as of the previous "
                "session, since a day's close and filings are not known mid-session."
            )

        if self.max_holding_days is not None:
            out.append(f"Positions are closed after {self.max_holding_days} sessions regardless.")
        if self.min_holding_days:
            out.append(
                f"Signal exits are suppressed for the first {self.min_holding_days} sessions of "
                "a position; protective exits are not."
            )
        if self.cooldown_days:
            out.append(
                f"After an exit, the same instrument cannot be re-entered for "
                f"{self.cooldown_days} sessions."
            )

        if self.price_adjustment == "split_dividend":
            out.append(
                "Splits and dividends: signals read prices back-adjusted for both, as of the "
                "run's end date. Trades fill at the prices that actually traded; a split "
                "multiplies the shares held, and a dividend is paid to a long (charged to a "
                "short) in cash on its ex-date -- the pay date is not modelled."
            )
        elif self.price_adjustment == "split":
            out.append(
                "Splits: signals read split-adjusted prices and a split multiplies the shares "
                "held. Dividends are ignored, so returns are price-only and a dividend shows up "
                "as a small real drop."
            )
        else:
            out.append(
                "Prices are unadjusted, so a split or dividend inside the window shows up as a "
                "real move."
            )
        if self.max_volume_participation is None:
            out.append("Fills assume unlimited liquidity at the modelled price.")
        out.append("No queue position, order-book depth or market impact is modelled.")
        return out

    def _allocation_assumptions(self, allocation: AllocationSettings) -> list[str]:
        out: list[str] = []
        exposure = (
            "Weights are normalised so gross exposure (longs plus shorts) targets "
            f"{allocation.target_exposure:.1%} of equity"
            + ("." if allocation.target_exposure >= 1 else "; the rest stays in cash.")
        )
        score = (
            "A signal's score is the weight of the entry components that fired divided by "
            "the weight of all entry components, so 1 means every entry component agreed; "
            "filters and exit components do not count."
        )
        if self.position_sizing == "equal_active":
            # The score does not set weights here, but it still decides who is
            # allocated when a minimum score or a position limit applies.
            ranks = allocation.min_score > 0 or self.max_positions is not None
            out.append(
                "Equal-active allocation: one shared pool of capital is split evenly across "
                "every instrument with an active entry signal. "
                + exposure
                + (
                    f" {score} The score does not change the weights, only which signals are "
                    "allocated."
                    if ranks
                    else ""
                )
            )
        elif self.position_sizing == "signal_strength":
            out.append(
                "Signal-strength allocation: one shared pool of capital is split across every "
                "instrument with an active entry signal in proportion to that signal's score. "
                f"{score} {exposure}"
            )
        else:
            out.append(
                "Signal-inverse-volatility allocation: one shared pool of capital is split "
                "across every instrument with an active entry signal in proportion to that "
                "signal's score divided by the instrument's trailing annualised volatility "
                f"of close-to-close returns over {self.atr_period} bars, so a calmer "
                f"instrument gets more capital. {score} An instrument whose volatility is not "
                f"yet defined, or is zero, gets no allocation. {exposure}"
            )
        out.append(
            "Capital is shared across positions: a new signal, a changed score or an exit "
            "elsewhere changes every target, so positions the strategy did not signal on "
            "can be bought up or trimmed. A strategy or protective exit drops the "
            "instrument from the allocation until it signals again."
        )
        if allocation.min_score > 0:
            out.append(
                f"Signals with a score below {allocation.min_score:.2f} (under "
                f"{allocation.min_score:.1%} of the entry-component weight agreeing) get no "
                "allocation."
            )
        if self.max_positions is not None:
            out.append(
                f"At most {self.max_positions} positions are allocated: when more instruments "
                "signal, the highest scores are kept (ties broken by symbol) and the rest get "
                "nothing."
            )
        if self.max_position_pct < 1.0:
            out.append(
                f"No single position's target exceeds {self.max_position_pct:.1%} of equity; "
                "weight above the cap is redistributed to the uncapped positions, and what "
                "cannot be placed stays in cash."
            )
        when = {
            "on_signal": "on each session whose signals change the allocation (a new "
            "entry, a changed score or an exit)",
            "daily": "every session",
            "weekly": "on the first session of each ISO week",
            "monthly": "on the first session of each calendar month",
        }[allocation.frequency]
        between = (
            ""
            if allocation.frequency in ("on_signal", "daily")
            else " Entry signals that arrive between rebalances wait for the next one."
        )
        out.append(
            f"Targets are recomputed {when}, from that session's signals, equity and closes "
            "after its exits, and positions are traded toward them: reductions and closes "
            "first, then increases. Strategy and protective exits are always taken when they "
            f"happen.{between} Each rebalance order's quantity is fixed when it is created; a "
            "deferred or volume-limited fill keeps that quantity rather than resizing to "
            "later prices."
        )
        if allocation.threshold > 0:
            out.append(
                f"A change smaller than {allocation.threshold:.1%} of equity between a "
                "position's current and target weight is not traded, so small drift is left "
                "alone; strategy and protective exits are never skipped."
            )
        if allocation.max_turnover is not None:
            out.append(
                f"Each rebalance trades at most {allocation.max_turnover:.1%} of equity in "
                "total weight change (the sum of absolute changes across positions); a larger "
                "rebalance has every discretionary change scaled down in proportion, so the "
                "book reaches its targets over several rebalances. Strategy and protective "
                "exits are neither counted nor scaled."
            )
        return out

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Every field, except allocation settings left unset.

        Omitting those keeps a legacy config's serialisation exactly what it
        was before they existed; ``from_dict`` restores them as ``None``.
        """
        from dataclasses import asdict

        out = asdict(self)
        for name in _ALLOCATION_FIELDS:
            if out[name] is None:
                del out[name]
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExecutionConfig:
        """Build from a request body, ignoring nothing silently.

        An unknown key is an error rather than a no-op: a user who misspells
        ``stop_loss_pct`` must not get a run that quietly had no stop.
        """
        if not data:
            return cls()
        known = {field for field in cls.__dataclass_fields__}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown execution setting(s): {', '.join(unknown)}")
        return cls(**data)

    def merged_with(self, overrides: dict[str, Any] | None) -> ExecutionConfig:
        if not overrides:
            return self
        known = {field for field in self.__dataclass_fields__}
        unknown = sorted(set(overrides) - known)
        if unknown:
            raise ValueError(f"unknown execution setting(s): {', '.join(unknown)}")
        return replace(self, **overrides)


#: What a new run gets when the caller says nothing: equal-weight sleeves,
#: next-open fills, base costs and no stops. A stored run recorded before
#: ``price_adjustment`` existed re-executes with it set to ``none``
#: (``research.runner.execution_config_for``), so its numbers do not move.
DEFAULT_EXECUTION = ExecutionConfig()
