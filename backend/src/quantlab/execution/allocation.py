"""Portfolio-level allocation: target weights for the shared-capital sizing modes.

The three shared-capital ``position_sizing`` modes (``equal_active``,
``signal_strength`` and ``signal_inverse_volatility``) do not size each entry on
its own. They keep one book of *target weights* across every held position and
trade towards it. This module is the arithmetic for that book and nothing
else: it takes plain values and returns plain values, and it knows nothing of
bars storage, the API or the execution engine. That keeps every formula here
testable by hand.

Weights are fractions of equity, signed: ``+0.25`` is a long position worth a
quarter of equity, ``-0.25`` a short of the same size.

Raw weights, before caps:

* ``equal_active``:              ``raw = sign``
* ``signal_strength``:           ``raw = sign * score``
* ``signal_inverse_volatility``: ``raw = sign * score / volatility``

They are normalised by ``sum(|raw|)`` and multiplied by ``target_exposure``, so
gross exposure is ``target_exposure`` unless ``max_position_pct`` makes that
impossible, in which case the remainder stays in cash.

Every iteration below runs in a fixed order (by score then symbol, or by
symbol), so the same inputs always give the same floats.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

#: Reserved ``trigger_values`` key that holds an entry decision's score.
SCORE_KEY = "_score"

#: The sizing modes this module allocates for.
ALLOCATION_MODES = ("equal_active", "signal_strength", "signal_inverse_volatility")

# Exclusion reasons reported in :attr:`TargetWeights.excluded`.
INVALID_SCORE = "invalid_score"
MIN_SCORE = "min_score"
NO_VOLATILITY = "no_volatility"
MAX_POSITIONS = "max_positions"


def _real(value: object) -> float | None:
    """``value`` as a finite float when it is a real number, else ``None``.

    Accepts numpy scalars (anything registered as :class:`numbers.Real`), but
    not bools: ``True`` is an ``int`` subclass, not a number to allocate by.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _valid_score(value: object) -> float | None:
    """``value`` as a float when it is a real number in ``(0, 1]``, else ``None``."""
    score = _real(value)
    if score is None or score <= 0.0 or score > 1.0:
        return None
    return score


def signal_score(trigger_values: Mapping[str, object]) -> float | None:
    """The allocation score stored on a decision's ``trigger_values``.

    A decision without a score (every run stored before scores existed) counts
    as full conviction, ``1.0``. A score that is present but is not a finite
    number in ``(0, 1]`` returns ``None``: the decision is not eligible for
    allocation.
    """
    if SCORE_KEY not in trigger_values:
        return 1.0
    return _valid_score(trigger_values[SCORE_KEY])


@dataclass(frozen=True)
class AllocationSignal:
    """One instrument's active entry signal, as the allocator sees it."""

    symbol: str
    direction: int  # +1 long, -1 short
    score: float
    volatility: float | None = None


@dataclass(frozen=True)
class TargetWeights:
    """The allocator's answer for one rebalance."""

    #: Signed target weight per selected symbol; ``sum(|w|) <= target_exposure``.
    weights: Mapping[str, float]
    #: Selected symbols, sorted by ``(-score, symbol)``.
    selected: tuple[str, ...]
    #: Symbol -> why it got no weight: ``"invalid_score"``, ``"min_score"``,
    #: ``"no_volatility"`` or ``"max_positions"``.
    excluded: Mapping[str, str]


def target_weights(
    signals: Sequence[AllocationSignal],
    *,
    mode: str,
    target_exposure: float,
    min_score: float = 0.0,
    max_positions: int | None = None,
    max_position_pct: float = 1.0,
) -> TargetWeights:
    """Signed target weights for the active signals under ``mode``.

    Eligibility, checked in this order:

    1. the score must be a finite number in ``(0, 1]`` (else ``"invalid_score"``);
    2. it must be at least ``min_score`` (else ``"min_score"``);
    3. in ``signal_inverse_volatility`` the volatility must be a finite
       positive number (else ``"no_volatility"``);
    4. with ``max_positions`` set, only the top N eligible signals by
       ``(-score, symbol)`` are kept (the rest get ``"max_positions"``).

    The kept signals' raw weights are normalised to ``target_exposure`` gross,
    then each absolute weight is capped at ``max_position_pct`` with the excess
    redistributed among the uncapped names (:func:`cap_and_redistribute`).

    Raises :class:`ValueError` naming the field for an unknown mode, a
    direction other than ``+1``/``-1``, a repeated symbol, or out-of-range
    exposure, minimum score, position count or cap.
    """
    if mode not in ALLOCATION_MODES:
        raise ValueError(f"position_sizing: {mode!r} is not an allocation mode")
    if not math.isfinite(target_exposure) or target_exposure < 0.0:
        raise ValueError("target_exposure must be a finite number >= 0")
    if not math.isfinite(max_position_pct) or max_position_pct <= 0.0:
        raise ValueError("max_position_pct must be a finite number > 0")
    if not math.isfinite(min_score) or not 0.0 <= min_score <= 1.0:
        raise ValueError("min_allocation_score must be a finite number in [0, 1]")
    if max_positions is not None and (
        isinstance(max_positions, bool)
        or not isinstance(max_positions, numbers.Integral)
        or max_positions < 0
    ):
        raise ValueError("max_positions must be an integer >= 0")

    excluded: dict[str, str] = {}
    # (score, magnitude |raw|, direction, symbol)
    eligible: list[tuple[float, float, int, str]] = []
    seen: set[str] = set()
    for signal in signals:
        if signal.symbol in seen:
            raise ValueError(f"symbol: {signal.symbol!r} appears more than once")
        seen.add(signal.symbol)
        direction = signal.direction
        if isinstance(direction, bool) or direction not in (1, -1):
            raise ValueError(f"direction: {signal.symbol!r} has {direction!r}, expected +1 or -1")
        score = _valid_score(signal.score)
        if score is None:
            excluded[signal.symbol] = INVALID_SCORE
            continue
        if score < min_score:
            excluded[signal.symbol] = MIN_SCORE
            continue
        if mode == "equal_active":
            magnitude = 1.0
        elif mode == "signal_strength":
            magnitude = score
        else:
            vol = _real(signal.volatility)
            # A volatility so small that score/vol overflows is as unusable as none.
            magnitude = score / vol if vol is not None and vol > 0.0 else math.inf
            if not math.isfinite(magnitude):
                excluded[signal.symbol] = NO_VOLATILITY
                continue
        eligible.append((score, magnitude, int(direction), signal.symbol))

    eligible.sort(key=lambda item: (-item[0], item[3]))
    if max_positions is not None:
        for *_, symbol in eligible[max_positions:]:
            excluded[symbol] = MAX_POSITIONS
        eligible = eligible[:max_positions]

    raw = {symbol: magnitude for _, magnitude, _, symbol in eligible}
    absolute = cap_and_redistribute(raw, total=target_exposure, cap=max_position_pct)
    selected = tuple(symbol for *_, symbol in eligible)
    # ``or 0.0`` turns a short's -0.0 (zero exposure) into a plain 0.0.
    weights = {
        symbol: (direction * absolute[symbol]) or 0.0 for _, _, direction, symbol in eligible
    }
    return TargetWeights(
        weights=weights,
        selected=selected,
        excluded=dict(sorted(excluded.items())),
    )


def cap_and_redistribute(raw: Mapping[str, float], *, total: float, cap: float) -> dict[str, float]:
    """Split ``total`` in proportion to ``raw``, with no name above ``cap``.

    Iterative water-fill: allocate the uncommitted total proportionally among
    the uncapped names; every name that lands above ``cap`` is pinned at
    ``cap`` and the rest is re-split among the others, until nothing new is
    pinned. When every name ends up pinned (``cap * n < total``) the remainder
    is left unallocated -- residual cash.

    Inputs must be non-negative. A name with raw weight 0 gets 0. The result
    has the same keys as ``raw``, in symbol order.
    """
    if not math.isfinite(total) or total < 0.0:
        raise ValueError("total must be a finite number >= 0")
    if not math.isfinite(cap) or cap < 0.0:
        raise ValueError("cap must be a finite number >= 0")
    symbols = sorted(raw)
    for symbol in symbols:
        value = raw[symbol]
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"raw: {symbol!r} has {value!r}, expected a finite number >= 0")

    out = {symbol: 0.0 for symbol in symbols}
    # Rescale by the largest raw so summing huge (finite) raws cannot overflow;
    # proportions, and so the result, are unchanged.
    peak = max(raw.values(), default=0.0)
    scaled = {symbol: raw[symbol] / peak for symbol in symbols} if peak > 0.0 else dict(raw)
    capped: set[str] = set()
    while True:
        free = [s for s in symbols if s not in capped and scaled[s] > 0.0]
        if not free:
            break
        remaining = total - cap * len(capped)
        if remaining <= 0.0:
            for symbol in free:  # nothing left for them: drop last round's shares
                out[symbol] = 0.0
            break
        free_raw = math.fsum(scaled[s] for s in free)
        newly_capped = False
        for symbol in free:
            share = remaining * scaled[symbol] / free_raw
            if share > cap:
                capped.add(symbol)
                newly_capped = True
            out[symbol] = share
        if not newly_capped:
            break
    for symbol in capped:
        out[symbol] = cap
    return out


@dataclass(frozen=True)
class RebalancePlan:
    """What a rebalance will trade."""

    #: Signed weight to trade to, per symbol that changes, in symbol order.
    targets: Mapping[str, float]
    #: Symbols whose change was smaller than the drift threshold, in symbol order.
    skipped: tuple[str, ...]
    #: Factor applied to every discretionary change; 1.0 when uncapped.
    turnover_scale: float


def plan_rebalance(
    current: Mapping[str, float],
    target: Mapping[str, float],
    *,
    threshold: float = 0.0,
    max_turnover: float | None = None,
    mandatory: Collection[str] = (),
) -> RebalancePlan:
    """Turn current and target weights into the changes to trade.

    A symbol held now but absent from ``target`` has target 0. For every
    *discretionary* symbol (not in ``mandatory``):

    * a change with ``|target - current| < threshold`` is skipped;
    * turnover is ``sum(|target - current|)`` over the changes that remain;
      when it exceeds ``max_turnover`` every one of those changes is scaled
      by ``max_turnover / turnover``.

    Symbols in ``mandatory`` (strategy or protective exits) always trade to
    their target in full: they ignore the threshold and are left out of both
    the turnover sum and the scaling.
    """
    if not math.isfinite(threshold) or threshold < 0.0:
        raise ValueError("rebalance_threshold must be a finite number >= 0")
    if max_turnover is not None and (not math.isfinite(max_turnover) or max_turnover < 0.0):
        raise ValueError("max_turnover must be a finite number >= 0")

    forced = set(mandatory)
    targets: dict[str, float] = {}
    skipped: list[str] = []
    discretionary: list[tuple[str, float, float]] = []  # (symbol, current, goal)
    for symbol in sorted(set(current) | set(target)):
        now = float(current.get(symbol, 0.0))
        goal = float(target.get(symbol, 0.0))
        if goal == now:
            continue
        if symbol in forced:
            targets[symbol] = goal
            continue
        delta = goal - now
        if abs(delta) < threshold:
            skipped.append(symbol)
            continue
        discretionary.append((symbol, now, goal))

    turnover = math.fsum(abs(goal - now) for _, now, goal in discretionary)
    scale = 1.0
    if max_turnover is not None and turnover > max_turnover:
        scale = max_turnover / turnover
    for symbol, now, goal in discretionary:
        # Unscaled changes trade to the exact target, not ``now + delta``.
        scaled = goal if scale == 1.0 else now + (goal - now) * scale
        if scaled != now:
            targets[symbol] = scaled

    return RebalancePlan(
        targets=dict(sorted(targets.items())),
        skipped=tuple(skipped),
        turnover_scale=scale,
    )
