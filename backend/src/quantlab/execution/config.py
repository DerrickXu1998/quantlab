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

#: Notional book size when the caller does not set one. Arbitrary but fixed:
#: every ratio the performance module reports is scale-invariant, so this only
#: sets the axis labels.
INITIAL_CAPITAL = 100_000.0

POSITION_SIZING: tuple[str, ...] = (
    "equal_weight",
    "fixed_fraction",
    "fixed_notional",
    "volatility_target",
)

FILL_TIMING: tuple[str, ...] = ("signal_close", "next_open")

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

    # --- timing and costs ---
    fill_timing: str = "signal_close"
    commission_bps: float = 0.0
    slippage_bps: float = 0.0

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

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if self.position_sizing not in POSITION_SIZING:
            raise ValueError(
                f"position_sizing must be one of {POSITION_SIZING}, got {self.position_sizing!r}"
            )
        if self.fill_timing not in FILL_TIMING:
            raise ValueError(
                f"fill_timing must be one of {FILL_TIMING}, got {self.fill_timing!r}"
            )

        # Modes that need a value must have one; equal_weight must not, because
        # silently ignoring a number the user typed is how a run quietly does
        # something other than what the form said.
        if self.position_sizing == "equal_weight":
            if self.sizing_value is not None:
                raise ValueError(
                    "sizing_value is not used by equal_weight sizing; leave it unset"
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

        _positive("commission_bps", self.commission_bps, allow_zero=True)
        _positive("slippage_bps", self.slippage_bps, allow_zero=True)

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

    # -- warm-up -----------------------------------------------------------

    @property
    def extra_lookback_days(self) -> int:
        """Bars of history the *execution* layer needs on top of the strategy's.

        An ATR stop is set from the ATR as at the entry bar, so a position
        opened on the first bar of the window still needs ``atr_period`` bars
        behind it or its stop would be undefined.
        """
        return self.atr_period + 1 if self.atr_stop_multiple is not None else 0

    # -- disclosure --------------------------------------------------------

    def assumptions(self) -> list[str]:
        """The caveats that actually apply to a run under this config.

        Generated rather than fixed, so the list travels with the numbers and
        cannot drift from them (the same stance the corporate-action warning
        takes).
        """
        out: list[str] = []

        if self.allow_shorts:
            out.append(
                "Long and short: a bearish entry opens a short and a bullish signal covers it. "
                "Borrow costs, locate availability and short-sale restrictions are not modelled."
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
        else:
            out.append(
                f"Volatility-targeted sizing: each position is scaled so its own realised "
                f"volatility contributes about {self.sizing_value:.1%} annualised, capped at "
                f"{self.max_position_pct:.0%} of equity."
            )

        if self.max_positions is not None:
            out.append(
                f"At most {self.max_positions} positions are held at once; a signal arriving "
                "when the book is full is dropped, not queued."
            )
        if self.max_position_pct < 1.0 and self.position_sizing != "equal_weight":
            out.append(f"No single position exceeds {self.max_position_pct:.0%} of equity.")

        if self.fill_timing == "signal_close":
            out.append("Signal entries and exits are marked at the close of the signal date.")
        else:
            out.append(
                "Signal entries and exits are filled at the open of the session after the "
                "signal date; a signal on the last bar of the window has no session to fill in "
                "and is dropped."
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

        out.append(
            "Prices are unadjusted, so a split or dividend inside the window shows up as a "
            "real move."
        )
        out.append(
            "Fills assume unlimited liquidity at the modelled price: no partial fills, no "
            "queue position, no market impact."
        )
        return out

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)

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


#: What a run gets when the caller says nothing. Chosen to reproduce the
#: behaviour that predates this module exactly -- equal-weight sleeves, filled
#: at the close of the signal date, no costs and no stops -- so a legacy request
#: still produces a legacy answer.
DEFAULT_EXECUTION = ExecutionConfig()
