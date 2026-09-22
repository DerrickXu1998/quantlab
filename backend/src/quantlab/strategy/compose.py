"""Turning a :class:`StrategySpec` into the decisions an execution run consumes.

Each component is evaluated on its own -- it is just a signal rule, and knows
nothing about the strategy it sits in -- and the per-date results are then
reduced by the strategy's combination logic.

Two things here are easy to get wrong and are worth stating plainly.

**Filters gate, they never fire.** A filter component contributes no entry of
its own; it can only prevent one. A strategy whose every component is a filter
is rejected at validation rather than quietly never trading.

**Filters do not gate exits.** If a filter shutting off could block an exit, a
position would be trapped in the book by the very condition that says the
regime has changed -- the exact moment you most want out. Exits answer only to
exit components and to the execution criteria.

Causality: a component is "active" on date T if it fired within the trailing
agreement window ending at T. The window only ever looks backwards, so nothing
here can see a bar it should not (Constitution VII).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from quantlab.execution.engine import Decision
from quantlab.strategy.spec import StrategyComponent, StrategySpec

#: The two directions, in the order decisions are emitted within a date.
_DIRECTIONS = ("bullish", "bearish")

#: Closing frees capital and a position slot, so it is resolved before anything
#: competes for either. ``both`` can do either job and sorts with the closers.
_KIND_ORDER = {"exit": 0, "both": 1, "entry": 2}


@dataclass(frozen=True)
class _Firing:
    """One component's event, flattened to what combination needs."""

    date: str
    direction: str
    trigger_values: dict[str, Any]
    data_window_end: str


@dataclass(frozen=True)
class CompositionStats:
    """What composition did, including what it refused to emit.

    ``contradictions`` is the interesting one: a strategy whose entry logic
    says both "go long" and "go short" on the same date has not expressed a
    view, and silently taking one side would be arbitrary.
    """

    dates_evaluated: int = 0
    entry_decisions: int = 0
    exit_decisions: int = 0
    contradictions: int = 0


def _fire_map(
    component: StrategyComponent,
    index: int,
    bars: list[Any],
    facts: Any = None,
) -> dict[str, _Firing]:
    """Run one component over one instrument's bars.

    Returns the last firing per date. A rule that emits twice on one date for
    one instrument is emitting a state, not an event, and only its final word
    on that date matters.

    ``facts`` is passed only to rules that declared they read them. Handing it
    to every rule would mean every existing rule had to grow a keyword it never
    uses, and the declaration is what the runner already keys on to decide
    which concepts to load.
    """
    rule = component.resolve(index)
    if len(bars) < rule.lookback_days:
        return {}
    parameters = rule.effective_params(component.parameters)
    if rule.requires_facts:
        parameters["facts"] = facts
    out: dict[str, _Firing] = {}
    for event in rule.compute(bars, **parameters):
        direction = event.direction
        if component.invert:
            direction = "bearish" if direction == "bullish" else "bullish"
        out[event.date] = _Firing(
            date=event.date,
            direction=direction,
            trigger_values=dict(event.trigger_values),
            data_window_end=event.data_window_end,
        )
    return out


def _active(
    fires: dict[str, _Firing], dates: list[str], window: int
) -> dict[str, dict[str, _Firing]]:
    """For each date, the firing of each direction still inside the window.

    ``window`` of 1 means "fired on this bar". Anything larger lets a
    confirmation land a few sessions after the trigger, which is what makes a
    two-oscillator strategy tradeable at all -- requiring two indicators to
    turn on the very same bar almost never happens.
    """
    out: dict[str, dict[str, _Firing]] = {}
    recent: dict[str, _Firing] = {}
    positions = {date: index for index, date in enumerate(dates)}
    for index, date in enumerate(dates):
        firing = fires.get(date)
        if firing is not None:
            recent[firing.direction] = firing
        live: dict[str, _Firing] = {}
        for direction, candidate in recent.items():
            age = index - positions.get(candidate.date, index)
            if age < window:
                live[direction] = candidate
        out[date] = live
    return out


def _members(
    components: list[tuple[int, StrategyComponent]],
    active_by_component: dict[int, dict[str, dict[str, _Firing]]],
    date: str,
) -> dict[str, list[tuple[int, StrategyComponent, _Firing]]]:
    """Which of ``components`` are active on ``date``, split by direction."""
    out: dict[str, list[tuple[int, StrategyComponent, _Firing]]] = {
        direction: [] for direction in _DIRECTIONS
    }
    for direction in _DIRECTIONS:
        for index, component in components:
            firing = active_by_component[index].get(date, {}).get(direction)
            if firing is not None:
                out[direction].append((index, component, firing))
    return out


def _combine(
    active: list[_Firing], total: int, weights: list[float], logic: str, threshold: float
) -> bool:
    """Reduce the components active in one direction to a yes or a no."""
    if total == 0 or not active:
        return False
    if logic == "all":
        return len(active) == total
    if logic == "any":
        return True
    if logic == "majority":
        return len(active) * 2 > total
    return sum(weights) >= threshold


def compose(
    spec: StrategySpec,
    bars_by_symbol: dict[str, list[Any]],
    symbols: Iterable[str] | None = None,
    facts_by_symbol: dict[str, Any] | None = None,
) -> tuple[list[Decision], CompositionStats]:
    """Evaluate ``spec`` over each instrument and emit its decisions.

    Output is sorted by ``(symbol, date, kind)`` so the same spec over the same
    bars produces a byte-identical decision list (Constitution VI).

    ``facts_by_symbol`` carries point-in-time fundamentals for the instruments
    that have them. A symbol missing from it simply has none, and the rules
    that read facts shut their gates rather than treating absence as zero
    (docs/FUNDAMENTALS.md §5.5).
    """
    selection = sorted(symbols) if symbols is not None else sorted(bars_by_symbol)
    entries = [(i, c) for i, c in enumerate(spec.components) if c.role == "entry"]
    exits = [(i, c) for i, c in enumerate(spec.components) if c.role == "exit"]
    filters = [(i, c) for i, c in enumerate(spec.components) if c.role == "filter"]

    decisions: list[Decision] = []
    dates_evaluated = 0
    contradictions = 0

    for symbol in selection:
        bars = bars_by_symbol.get(symbol) or []
        if not bars:
            continue
        dates = [bar.date for bar in bars]
        window = spec.combine_window_days

        facts = (facts_by_symbol or {}).get(symbol)
        active_by_component = {
            index: _active(_fire_map(component, index, bars, facts), dates, window)
            for index, component in enumerate(spec.components)
        }

        for date in dates:
            dates_evaluated += 1

            # Filters are evaluated once and gate every entry on the date,
            # whichever way it points: "there is a trend here" qualifies a
            # short exactly as much as a long.
            gate_open = all(
                "bullish" in active_by_component[index].get(date, {})
                for index, _ in filters
            )

            entry_members = _members(entries, active_by_component, date)
            exit_members = _members(exits, active_by_component, date)

            wants_entry = {
                direction: _combine(
                    [f for _, _, f in entry_members[direction]],
                    len(entries),
                    [c.weight for _, c, _ in entry_members[direction]],
                    spec.entry_logic,
                    spec.entry_threshold,
                )
                for direction in _DIRECTIONS
            }
            wants_exit = {
                direction: _combine(
                    [f for _, _, f in exit_members[direction]],
                    len(exits),
                    [c.weight for _, c, _ in exit_members[direction]],
                    spec.exit_logic,
                    spec.exit_threshold,
                )
                for direction in _DIRECTIONS
            }

            if wants_entry["bullish"] and wants_entry["bearish"]:
                # No view. Emitting one side would be a coin flip dressed as a
                # signal, so neither side is emitted.
                contradictions += 1
                wants_entry = dict.fromkeys(_DIRECTIONS, False)

            for direction in _DIRECTIONS:
                # The gate stops an entry. It never stops an exit -- a filter
                # switching off must not trap a position in the book.
                entry_ok = wants_entry[direction] and gate_open
                exit_ok = wants_exit[direction]
                if not entry_ok and not exit_ok:
                    continue
                if entry_ok and exit_ok:
                    # One rule wearing both hats, which is what a single-model
                    # run is. Emitted as one decision, so a legacy run records
                    # exactly the signals it always did rather than two rows
                    # per event.
                    kind = "both"
                    members = entry_members[direction] + exit_members[direction]
                elif entry_ok:
                    kind, members = "entry", entry_members[direction]
                else:
                    kind, members = "exit", exit_members[direction]
                decisions.append(
                    _decision(
                        date, symbol, kind, direction, members,
                        filters if kind != "exit" else (),
                        active_by_component, spec,
                    )
                )

    decisions.sort(key=lambda d: (d.symbol, d.date, _KIND_ORDER[d.kind], d.direction))
    stats = CompositionStats(
        dates_evaluated=dates_evaluated,
        entry_decisions=sum(1 for d in decisions if d.kind in ("entry", "both")),
        exit_decisions=sum(1 for d in decisions if d.kind in ("exit", "both")),
        contradictions=contradictions,
    )
    return decisions, stats


def _decision(
    date: str,
    symbol: str,
    kind: str,
    direction: str,
    members: list[tuple[int, StrategyComponent, _Firing]],
    filters: Iterable[tuple[int, StrategyComponent]],
    active_by_component: dict[int, dict[str, dict[str, _Firing]]],
    spec: StrategySpec,
) -> Decision:
    """Build one decision, carrying why it fired.

    ``trigger_values`` is namespaced by rule so two components of the same kind
    cannot overwrite each other's evidence, and so a user reading a signal can
    see which part of their strategy produced it.
    """
    trigger: dict[str, Any] = {}
    window_end = date
    for _, component, firing in members:
        for key, value in firing.trigger_values.items():
            trigger[f"{component.rule_name}.{key}"] = value
        if firing.data_window_end > window_end:  # pragma: no cover - defensive
            window_end = firing.data_window_end

    for index, component in filters:
        firing = active_by_component[index].get(date, {}).get("bullish")
        if firing is not None:
            for key, value in firing.trigger_values.items():
                trigger[f"{component.rule_name}.{key}"] = value

    trigger["_logic"] = spec.exit_logic if kind == "exit" else spec.entry_logic
    trigger["_components"] = [component.rule_name for _, component, _ in members]

    # data_window_end can never exceed the decision date: every contributing
    # firing is dated on or before it, and each carries a window end no later
    # than its own date. The database CHECK enforces the same invariant.
    return Decision(
        date=date,
        symbol=symbol,
        kind=kind,
        direction=direction,
        trigger_values=trigger,
        data_window_end=min(window_end, date),
    )
