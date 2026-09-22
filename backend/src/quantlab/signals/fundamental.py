"""Signal rules that read filed company accounts rather than the tape.

These are the rules that make `storage/facts.py` reachable from a strategy.
Everything about *when* a number may be used lives in that module; everything
here is about what to do with it.

Three things make these different from every other rule in the catalogue, and
each one shows up in the code below:

**They can be unknown.** A technical rule always has a close. A fundamental one
may have no filed equity at all — 64 of the 644 catalogued names have no
fundamentals whatsoever — and *unknown is not zero*. A missing book value does
not make a name cheap; it makes the gate shut. Every helper here returns None
rather than a default, and every gate treats None as closed.

**They go stale.** A close is from today. A balance sheet is from up to a year
ago, and a company that stopped filing in 2019 should not be gating a 2024
trade on its last known numbers. Every rule takes `max_stale_days` and the
default is deliberately finite.

**They step a few times a year.** A filter reads `facts.value()`, which is
forward-filled, so it is defined on every bar. A *change* signal reads
`facts.history()`, which is a list of periods, because "revenue grew" compares
two accounting periods — comparing two dates would report an ordinary
restatement as growth in the business (docs/FUNDAMENTALS.md §2).

Causality holds for the same reason it holds elsewhere: a rule asked about bar
`i` reads facts as of `bars[i].date`, and `FactSeries` will not return anything
filed after that date. The truncation sweep covers these rules automatically.
"""

from __future__ import annotations

from typing import Any

from quantlab.signals.registry import ParamSpec, SignalEvent, register_signal_rule

#: How old a filed figure may be before a gate stops trusting it.
#:
#: A year plus a quarter: an annual report is stale by up to a year in the
#: ordinary course, and a company filing on time will always have refreshed
#: within 15 months. Past that, the forward-fill is carrying a number from a
#: company that has stopped reporting.
DEFAULT_MAX_STALE_DAYS = 455


def _stale_spec() -> ParamSpec:
    return ParamSpec(
        name="max_stale_days",
        type="int",
        default=DEFAULT_MAX_STALE_DAYS,
        minimum=1,
        maximum=3650,
        description=(
            "Ignore a filed figure older than this many days. Stops a company "
            "that stopped reporting from gating today's trade on its last "
            "balance sheet."
        ),
    )


def _value(facts, concept: str, on: str, max_stale_days: int) -> float | None:
    """One concept's value, or None when it is unknown or too old."""
    if facts is None:
        return None
    fact = facts.value(concept, on, max_stale_days=max_stale_days)
    return None if fact is None else fact.value


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """A ratio, or None when either side is unknown or the divisor is degenerate.

    A zero or negative denominator is *not* an extreme ratio, it is an
    undefined one: a company with negative equity has no meaningful
    price-to-book, and letting the division produce a large negative number
    would make it pass a "cheap" filter.
    """
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _gate_events(bars, open_on: list[bool], trigger: list[dict[str, Any]]):
    """Turn a per-bar boolean gate into filter events.

    Same contract as the technical filters in ``library.py``: bullish means the
    gate is open on this date, bearish means shut, and a bar before the figure
    is known is shut rather than open.
    """
    return [
        SignalEvent(
            date=bar.date,
            direction="bullish" if open_on[i] else "bearish",
            trigger_values=trigger[i],
            data_window_end=bar.date,
        )
        for i, bar in enumerate(bars)
    ]


def _market_cap(bars, i: int, facts, on: str, max_stale_days: int) -> float | None:
    shares = _value(facts, "shares_outstanding", on, max_stale_days)
    if shares is None or shares <= 0:
        return None
    return bars[i].close * shares


# ---------------------------------------------------------------------------
# Valuation filters
# ---------------------------------------------------------------------------


@register_signal_rule(
    name="pe-filter",
    version="1.0.0",
    category="fundamental",
    summary="Gate that opens while the price-to-earnings ratio sits in a band.",
    roles=("filter",),
    requires_facts=("net_income", "shares_outstanding"),
    params={
        "min_pe": ParamSpec(
            name="min_pe", type="float", default=0.0, minimum=0.0, maximum=1000.0,
            description="Lowest P/E for which the gate is open. 0 admits anything profitable.",
        ),
        "max_pe": ParamSpec(
            name="max_pe", type="float", default=25.0, minimum=0.1, maximum=1000.0,
            description="Highest P/E for which the gate is open.",
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "A filter, so it emits on every bar: bullish while trailing P/E is within "
        "[min_pe, max_pe], bearish outside it. Earnings are the annual figure as "
        "last filed, so the ratio steps on filing dates, not daily. A loss-making "
        "company has no P/E and the gate is shut -- negative earnings are not a "
        "low multiple."
    ),
)
def pe_filter(
    bars,
    *,
    facts=None,
    min_pe: float = 0.0,
    max_pe: float = 25.0,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    open_on: list[bool] = []
    trigger: list[dict[str, Any]] = []
    for i, bar in enumerate(bars):
        earnings = _value(facts, "net_income", bar.date, max_stale_days)
        cap = _market_cap(bars, i, facts, bar.date, max_stale_days)
        pe = _ratio(cap, earnings)
        open_on.append(pe is not None and min_pe <= pe <= max_pe)
        trigger.append({"pe_ratio": round(pe, 4)} if pe is not None else {"pe_ratio": None})
    return _gate_events(bars, open_on, trigger)


@register_signal_rule(
    name="pb-filter",
    version="1.0.0",
    category="fundamental",
    summary="Gate that opens while price-to-book sits in a band.",
    roles=("filter",),
    requires_facts=("equity", "shares_outstanding"),
    params={
        "min_pb": ParamSpec(
            name="min_pb", type="float", default=0.0, minimum=0.0, maximum=100.0,
            description="Lowest price-to-book for which the gate is open.",
        ),
        "max_pb": ParamSpec(
            name="max_pb", type="float", default=3.0, minimum=0.01, maximum=100.0,
            description="Highest price-to-book for which the gate is open.",
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "A filter: bullish while price-to-book is within [min_pb, max_pb]. Book "
        "value is shareholders' equity as last filed. A company with negative "
        "equity has no meaningful book value and the gate is shut rather than "
        "reading as very cheap."
    ),
)
def pb_filter(
    bars,
    *,
    facts=None,
    min_pb: float = 0.0,
    max_pb: float = 3.0,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    open_on: list[bool] = []
    trigger: list[dict[str, Any]] = []
    for i, bar in enumerate(bars):
        equity = _value(facts, "equity", bar.date, max_stale_days)
        cap = _market_cap(bars, i, facts, bar.date, max_stale_days)
        pb = _ratio(cap, equity)
        open_on.append(pb is not None and min_pb <= pb <= max_pb)
        trigger.append({"pb_ratio": round(pb, 4)} if pb is not None else {"pb_ratio": None})
    return _gate_events(bars, open_on, trigger)


# ---------------------------------------------------------------------------
# Quality and solvency filters
# ---------------------------------------------------------------------------


@register_signal_rule(
    name="profitability-filter",
    version="1.0.0",
    category="fundamental",
    summary="Gate that opens while return on equity clears a floor.",
    roles=("filter",),
    requires_facts=("net_income", "equity"),
    params={
        "min_roe": ParamSpec(
            name="min_roe", type="float", default=0.10, minimum=-1.0, maximum=5.0,
            description="Minimum return on equity, as a fraction: 0.10 is 10%.",
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "A filter: bullish while net income over shareholders' equity is at or "
        "above min_roe. Needs no price, so it steps only when accounts are filed."
    ),
)
def profitability_filter(
    bars,
    *,
    facts=None,
    min_roe: float = 0.10,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    open_on: list[bool] = []
    trigger: list[dict[str, Any]] = []
    for bar in bars:
        roe = _ratio(
            _value(facts, "net_income", bar.date, max_stale_days),
            _value(facts, "equity", bar.date, max_stale_days),
        )
        open_on.append(roe is not None and roe >= min_roe)
        trigger.append({"roe": round(roe, 4)} if roe is not None else {"roe": None})
    return _gate_events(bars, open_on, trigger)


@register_signal_rule(
    name="leverage-filter",
    version="1.0.0",
    category="fundamental",
    summary="Gate that opens while debt-to-equity stays under a ceiling.",
    roles=("filter",),
    requires_facts=("long_term_debt", "equity"),
    params={
        "max_ratio": ParamSpec(
            name="max_ratio", type="float", default=1.0, minimum=0.0, maximum=100.0,
            description="Highest long-term debt to equity for which the gate is open.",
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "A filter: bullish while long-term debt over equity is at or below "
        "max_ratio. A company with negative equity is shut out, which is the "
        "intent -- it is the most leveraged state there is, not an absent one."
    ),
)
def leverage_filter(
    bars,
    *,
    facts=None,
    max_ratio: float = 1.0,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    open_on: list[bool] = []
    trigger: list[dict[str, Any]] = []
    for bar in bars:
        debt = _value(facts, "long_term_debt", bar.date, max_stale_days)
        equity = _value(facts, "equity", bar.date, max_stale_days)
        ratio = _ratio(debt, equity)
        # Debt of zero is a real, and very good, answer: no leverage at all.
        if ratio is None and debt == 0 and equity is not None and equity > 0:
            ratio = 0.0
        open_on.append(ratio is not None and ratio <= max_ratio)
        trigger.append(
            {"debt_to_equity": round(ratio, 4)} if ratio is not None else {"debt_to_equity": None}
        )
    return _gate_events(bars, open_on, trigger)


@register_signal_rule(
    name="margin-filter",
    version="1.0.0",
    category="fundamental",
    summary="Gate that opens while the operating margin clears a floor.",
    roles=("filter",),
    requires_facts=("operating_income", "revenue"),
    params={
        "min_margin": ParamSpec(
            name="min_margin", type="float", default=0.10, minimum=-1.0, maximum=1.0,
            description="Minimum operating margin, as a fraction: 0.10 is 10%.",
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "A filter: bullish while operating income over revenue is at or above "
        "min_margin. Both are annual figures from the same filing, so the two "
        "sides of the ratio always describe the same period."
    ),
)
def margin_filter(
    bars,
    *,
    facts=None,
    min_margin: float = 0.10,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    open_on: list[bool] = []
    trigger: list[dict[str, Any]] = []
    for bar in bars:
        margin = _ratio(
            _value(facts, "operating_income", bar.date, max_stale_days),
            _value(facts, "revenue", bar.date, max_stale_days),
        )
        open_on.append(margin is not None and margin >= min_margin)
        trigger.append(
            {"operating_margin": round(margin, 4) if margin is not None else None}
        )
    return _gate_events(bars, open_on, trigger)


@register_signal_rule(
    name="liquidity-filter",
    version="1.0.0",
    category="fundamental",
    summary="Gate that opens while the current ratio clears a floor.",
    roles=("filter",),
    requires_facts=("current_assets", "current_liabilities"),
    params={
        "min_ratio": ParamSpec(
            name="min_ratio", type="float", default=1.0, minimum=0.0, maximum=100.0,
            description="Minimum current assets to current liabilities.",
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "A filter: bullish while current assets over current liabilities is at "
        "or above min_ratio -- whether the company can cover the next year's "
        "obligations out of what it already holds."
    ),
)
def liquidity_filter(
    bars,
    *,
    facts=None,
    min_ratio: float = 1.0,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    open_on: list[bool] = []
    trigger: list[dict[str, Any]] = []
    for bar in bars:
        ratio = _ratio(
            _value(facts, "current_assets", bar.date, max_stale_days),
            _value(facts, "current_liabilities", bar.date, max_stale_days),
        )
        open_on.append(ratio is not None and ratio >= min_ratio)
        trigger.append(
            {"current_ratio": round(ratio, 4)} if ratio is not None else {"current_ratio": None}
        )
    return _gate_events(bars, open_on, trigger)


# ---------------------------------------------------------------------------
# Change signals
# ---------------------------------------------------------------------------
#
# These read `history()` rather than `value()`. Growth is a statement about two
# accounting *periods*; measuring it between two dates would call an ordinary
# restatement a change in the business.


def _fires_on_filing(bars, facts, decide) -> list[SignalEvent]:
    """Emit at most one event per bar, on the date a new period first appears.

    A change signal must fire when the information arrives, which is the filing
    date -- not on every subsequent bar for which the comparison still holds.
    Tracking the newest period seen turns a standing condition into an event.
    """
    if facts is None:
        return []
    events: list[SignalEvent] = []
    seen: str | None = None
    for bar in bars:
        outcome = decide(bar.date)
        if outcome is None:
            continue
        period_end, direction, trigger = outcome
        if period_end == seen:
            continue
        seen = period_end
        events.append(
            SignalEvent(
                date=bar.date,
                direction=direction,
                trigger_values=trigger,
                data_window_end=bar.date,
            )
        )
    return events


@register_signal_rule(
    name="revenue-growth",
    version="1.0.0",
    category="fundamental",
    summary="Fires when year-on-year revenue growth crosses a threshold.",
    roles=("entry", "exit"),
    requires_facts=("revenue",),
    params={
        "threshold": ParamSpec(
            name="threshold", type="float", default=0.10, minimum=-1.0, maximum=10.0,
            description="Growth that counts as accelerating, as a fraction: 0.10 is 10%.",
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "bullish: the newest filed period grew revenue by at least `threshold` "
        "against the period before it; bearish: it shrank by at least that much. "
        "Fires once, on the bar where the new filing first became visible -- not "
        "on every bar the comparison still holds."
    ),
)
def revenue_growth(
    bars,
    *,
    facts=None,
    threshold: float = 0.10,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    def decide(on: str):
        periods = facts.history("revenue", on, limit=2)
        if len(periods) < 2:
            return None
        previous, latest = periods[-2], periods[-1]
        if latest.days_stale(on) > max_stale_days or previous.value <= 0:
            return None
        growth = latest.value / previous.value - 1.0
        if growth >= threshold:
            direction = "bullish"
        elif growth <= -threshold:
            direction = "bearish"
        else:
            return None
        return latest.period_end, direction, {
            "revenue_growth": round(growth, 4),
            "period": latest.period_end,
            "prior_period": previous.period_end,
        }

    return _fires_on_filing(bars, facts, decide)


@register_signal_rule(
    name="margin-expansion",
    version="1.0.0",
    category="fundamental",
    summary="Fires when the operating margin improves for consecutive periods.",
    roles=("entry", "exit"),
    requires_facts=("operating_income", "revenue"),
    params={
        "periods": ParamSpec(
            name="periods", type="int", default=2, minimum=2, maximum=8,
            description="How many consecutive filed periods must move the same way.",
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "bullish: the operating margin rose in each of the last `periods` filed "
        "periods; bearish: it fell in each. A run of improving margins is the "
        "claim, so one good quarter after several bad ones does not fire."
    ),
)
def margin_expansion(
    bars,
    *,
    facts=None,
    periods: int = 2,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    def decide(on: str):
        income = facts.history("operating_income", on, limit=periods + 1)
        revenue = facts.history("revenue", on, limit=periods + 1)
        by_period = {fact.period_end: fact.value for fact in revenue}
        margins: list[tuple[str, float]] = []
        for fact in income:
            turnover = by_period.get(fact.period_end)
            if turnover is None or turnover <= 0:
                continue
            margins.append((fact.period_end, fact.value / turnover))
        if len(margins) < periods + 1:
            return None
        window = margins[-(periods + 1) :]
        if window[-1][0] and facts.value("revenue", on, max_stale_days=max_stale_days) is None:
            return None
        deltas = [b[1] - a[1] for a, b in zip(window, window[1:], strict=True)]
        if all(delta > 0 for delta in deltas):
            direction = "bullish"
        elif all(delta < 0 for delta in deltas):
            direction = "bearish"
        else:
            return None
        return window[-1][0], direction, {
            "operating_margin": round(window[-1][1], 4),
            "change": round(deltas[-1], 4),
            "periods": periods,
        }

    return _fires_on_filing(bars, facts, decide)


@register_signal_rule(
    name="accrual-reversal",
    version="1.0.0",
    category="fundamental",
    summary="Fires when cash flow and reported earnings diverge.",
    roles=("entry", "exit"),
    requires_facts=("operating_cash_flow", "net_income"),
    params={
        "threshold": ParamSpec(
            name="threshold", type="float", default=0.25, minimum=0.01, maximum=5.0,
            description=(
                "How far cash flow must diverge from earnings, as a fraction of "
                "earnings: 0.25 is 25%."
            ),
        ),
        "max_stale_days": _stale_spec(),
    },
    lookback_days=1,
    scale_class="scale_free",
    direction_semantics=(
        "bearish: operating cash flow falls short of reported net income by more "
        "than `threshold` -- earnings the business has not yet collected; "
        "bullish: cash flow exceeds earnings by that margin. A large accrual is "
        "the classic sign that reported profit is running ahead of cash."
    ),
)
def accrual_reversal(
    bars,
    *,
    facts=None,
    threshold: float = 0.25,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[SignalEvent]:
    def decide(on: str):
        earnings = facts.value("net_income", on, max_stale_days=max_stale_days)
        cash = facts.value("operating_cash_flow", on, max_stale_days=max_stale_days)
        if earnings is None or cash is None or earnings.value <= 0:
            return None
        # Compared within one period: a cash flow from a different year would
        # make the gap an artefact of the calendar rather than of accruals.
        if cash.period_end != earnings.period_end:
            return None
        gap = (cash.value - earnings.value) / earnings.value
        if gap <= -threshold:
            direction = "bearish"
        elif gap >= threshold:
            direction = "bullish"
        else:
            return None
        return earnings.period_end, direction, {
            "cash_vs_earnings": round(gap, 4),
            "period": earnings.period_end,
        }

    return _fires_on_filing(bars, facts, decide)
