"""Strategy specs and composition.

The behaviours worth protecting here are the ones that are easy to get subtly
wrong and impossible to notice afterwards: that a filter can gate an entry but
never open one, that a filter can never block an exit, and that a single-model
run still records exactly the signals it always did.
"""

from __future__ import annotations

import pytest

from quantlab.execution import ExecutionConfig, simulate
from quantlab.signals.registry import get_rule
from quantlab.strategy import (
    StrategyComponent,
    StrategySpec,
    StrategyValidationError,
    catalogue,
    compose,
    promote_legacy,
    template,
)
from quantlab.strategy.templates import TEMPLATE_IDS
from quantlab.synthetic.generator import Bar


def _path(seed: int, n: int = 400):
    import numpy as np

    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0004, 0.018, n) + 0.016 * np.sin(np.arange(n) / 12.0)
    closes = 100 * np.exp(np.cumsum(steps))
    out = []
    for i, close in enumerate(closes):
        high = close * (1 + abs(rng.normal(0, 0.013)))
        low = close * (1 - abs(rng.normal(0, 0.013)))
        open_ = float(min(max(close * (1 + rng.normal(0, 0.007)), low), high))
        volume = int(1e6 * (1 + abs(rng.normal(0, 0.6))))
        out.append(Bar(f"d{i:04d}", open_, float(high), float(low), float(close), volume))
    return out


@pytest.fixture
def series():
    return {symbol: _path(index + 21) for index, symbol in enumerate(("AAA", "BBB"))}


def component(rule, role, **parameters):
    return StrategyComponent(rule_name=rule, role=role, parameters=parameters)


def spec(*components, **kwargs):
    return StrategySpec(name=kwargs.pop("name", "test"), components=components, **kwargs)


# --- validation -------------------------------------------------------------


def test_a_filter_cannot_be_wired_as_an_entry():
    """The rule advertises its roles; the spec is refused if it disagrees."""
    with pytest.raises(StrategyValidationError, match="cannot be used as an 'entry'"):
        spec(component("adx-trend-filter", "entry"))


def test_a_strategy_of_only_filters_is_refused():
    with pytest.raises(StrategyValidationError, match="at least one entry component"):
        spec(component("rsi-threshold", "exit"), component("adx-trend-filter", "filter"))


def test_an_unknown_rule_names_itself():
    with pytest.raises(StrategyValidationError, match="unknown signal rule 'nope'"):
        spec(component("nope", "entry"))


def test_a_bad_parameter_names_the_component_and_the_field():
    with pytest.raises(StrategyValidationError, match=r"components\[0\].parameters.period"):
        spec(component("rsi-threshold", "entry", period=9999))


def test_a_misspelled_parameter_is_refused_rather_than_ignored():
    with pytest.raises(StrategyValidationError, match="has no parameter 'perriod'"):
        spec(component("rsi-threshold", "entry", perriod=14))


def test_an_unreachable_weighted_threshold_is_refused():
    """A threshold no combination of weights can reach is not a strict
    strategy, it is one that never trades."""
    with pytest.raises(StrategyValidationError, match="exceeds the total entry weight"):
        spec(
            component("rsi-threshold", "entry"),
            entry_logic="weighted",
            entry_threshold=99.0,
        )


def test_an_empty_strategy_is_refused():
    with pytest.raises(StrategyValidationError, match="at least one component"):
        spec()


def test_warnings_flag_the_legal_but_probably_unintended():
    no_exit = spec(component("rsi-threshold", "entry"))
    assert any("never closed" in w for w in no_exit.warnings)

    with_stop = spec(
        component("rsi-threshold", "entry"),
        execution=ExecutionConfig(stop_loss_pct=0.05),
    )
    assert any("only by the execution criteria" in w for w in with_stop.warnings)


# --- combination ------------------------------------------------------------


def test_a_filter_can_only_remove_entries_never_add_one(series):
    """The headline case: RSI on its own, then RSI gated by a trend filter.

    Stated as a subset rather than a strict inequality, because whether a given
    filter actually bites on a given price path is a property of the data. What
    must hold on every path is that gating never *invents* an entry.
    """
    unfiltered = spec(
        component("rsi-threshold", "entry"), component("rsi-threshold", "exit")
    )
    filtered = spec(
        component("rsi-threshold", "entry"),
        component("rsi-threshold", "exit"),
        component("adx-trend-filter", "filter", threshold=25.0),
    )

    def entries(strategy):
        decisions, _ = compose(strategy, series)
        return {
            (d.symbol, d.date, d.direction)
            for d in decisions
            if d.kind in ("entry", "both")
        }

    assert entries(filtered) <= entries(unfiltered)

    # And it does bite once the gate is demanding enough to matter.
    demanding = spec(
        component("rsi-threshold", "entry"),
        component("rsi-threshold", "exit"),
        component("adx-trend-filter", "filter", threshold=60.0),
    )
    assert len(entries(demanding)) < len(entries(unfiltered))


def test_gating_an_entry_never_changes_the_exits(series):
    plain = spec(component("rsi-threshold", "entry"), component("rsi-threshold", "exit"))
    gated = spec(
        component("rsi-threshold", "entry"),
        component("rsi-threshold", "exit"),
        component("adx-trend-filter", "filter", threshold=60.0),
    )

    def exits(strategy):
        decisions, _ = compose(strategy, series)
        return {
            (d.symbol, d.date, d.direction)
            for d in decisions
            if d.kind in ("exit", "both")
        }

    assert exits(gated) == exits(plain)


def test_a_shut_filter_blocks_every_entry_but_no_exit(series):
    """A filter that never opens must not trap a position in the book."""
    shut = spec(
        component("rsi-threshold", "entry"),
        component("rsi-threshold", "exit"),
        # ADX above 99 essentially never happens.
        component("adx-trend-filter", "filter", threshold=99.0),
    )
    _, stats = compose(shut, series)
    assert stats.entry_decisions == 0
    assert stats.exit_decisions > 0


def test_all_is_stricter_than_any(series):
    components = (
        component("rsi-threshold", "entry"),
        component("macd-crossover", "entry"),
        component("rsi-threshold", "exit"),
    )
    _, loose = compose(spec(*components, entry_logic="any", combine_window_days=5), series)
    _, strict = compose(spec(*components, entry_logic="all", combine_window_days=5), series)
    assert strict.entry_decisions <= loose.entry_decisions


def test_majority_sits_between_any_and_all(series):
    components = (
        component("rsi-threshold", "entry"),
        component("macd-crossover", "entry"),
        component("ema-crossover", "entry"),
        component("rsi-threshold", "exit"),
    )
    counts = {}
    for logic in ("all", "majority", "any"):
        _, stats = compose(
            spec(*components, entry_logic=logic, combine_window_days=10), series
        )
        counts[logic] = stats.entry_decisions
    assert counts["all"] <= counts["majority"] <= counts["any"]


def test_a_wider_agreement_window_can_only_add_agreement(series):
    components = (
        component("rsi-threshold", "entry"),
        component("macd-crossover", "entry"),
        component("rsi-threshold", "exit"),
    )
    _, tight = compose(spec(*components, entry_logic="all", combine_window_days=1), series)
    _, wide = compose(spec(*components, entry_logic="all", combine_window_days=20), series)
    assert wide.entry_decisions >= tight.entry_decisions


def test_weighted_logic_respects_the_threshold(series):
    """RSI carries weight 2, MACD weight 1. A threshold of 2 lets RSI act
    alone; a threshold of 3 requires both."""
    components = (
        StrategyComponent("rsi-threshold", role="entry", weight=2.0),
        StrategyComponent("macd-crossover", role="entry", weight=1.0),
        StrategyComponent("rsi-threshold", role="exit"),
    )
    _, alone = compose(
        spec(*components, entry_logic="weighted", entry_threshold=2.0,
             combine_window_days=5),
        series,
    )
    _, together = compose(
        spec(*components, entry_logic="weighted", entry_threshold=3.0,
             combine_window_days=5),
        series,
    )
    assert together.entry_decisions < alone.entry_decisions


def test_invert_swaps_a_components_directions(series):
    plain = spec(component("rsi-threshold", "entry"), component("rsi-threshold", "exit"))
    flipped = spec(
        StrategyComponent("rsi-threshold", role="entry", invert=True),
        component("rsi-threshold", "exit"),
    )
    straight, _ = compose(plain, series)
    inverted, _ = compose(flipped, series)

    straight_bullish = {(d.symbol, d.date) for d in straight if d.direction == "bullish"}
    inverted_bearish = {(d.symbol, d.date) for d in inverted if d.direction == "bearish"}
    assert straight_bullish and straight_bullish <= inverted_bearish


def test_contradictory_entries_emit_nothing(series):
    """A strategy that says both "long" and "short" on one date has not
    expressed a view, so neither side is taken."""
    contradiction = spec(
        StrategyComponent("rsi-threshold", role="entry"),
        StrategyComponent("rsi-threshold", role="entry", invert=True),
        entry_logic="any",
        combine_window_days=30,
    )
    decisions, stats = compose(contradiction, series)
    assert stats.contradictions > 0
    per_date: dict[tuple[str, str], set[str]] = {}
    for item in decisions:
        if item.kind in ("entry", "both"):
            per_date.setdefault((item.symbol, item.date), set()).add(item.direction)
    assert all(len(directions) == 1 for directions in per_date.values())


# --- provenance and determinism --------------------------------------------


def test_trigger_values_are_namespaced_by_rule(series):
    composed, _ = compose(
        spec(
            component("rsi-threshold", "entry"),
            component("macd-crossover", "entry"),
            component("rsi-threshold", "exit"),
            entry_logic="any",
        ),
        series,
    )
    keys = {key for item in composed for key in item.trigger_values}
    assert "rsi-threshold.rsi" in keys
    assert "macd-crossover.macd" in keys
    assert "_logic" in keys and "_components" in keys


def test_no_decision_is_built_from_a_later_bar(series):
    """Point-in-time, Constitution VII, at the composition layer."""
    for template_id in TEMPLATE_IDS:
        composed, _ = compose(template(template_id), series)
        assert all(item.data_window_end <= item.date for item in composed)


def test_composition_is_deterministic(series):
    first, _ = compose(template("dual-confirmation"), series)
    second, _ = compose(template("dual-confirmation"), series)
    assert first == second


# --- legacy compatibility ---------------------------------------------------


@pytest.mark.parametrize(
    "rule_name", ["rsi-threshold", "sma-crossover", "breakout-20d", "macd-crossover"]
)
def test_a_promoted_legacy_run_emits_one_decision_per_rule_event(rule_name, series):
    """A single-model run must record exactly the signals it always did, not
    two rows per event just because the rule now fills two roles."""
    rule = get_rule(rule_name)
    raw = sum(len(rule.compute(bars, **rule.params)) for bars in series.values())
    decisions, _ = compose(promote_legacy(rule_name), series)
    assert len(decisions) == raw
    assert {item.kind for item in decisions} == {"both"}


def test_promotion_wires_the_rule_into_both_roles():
    promoted = promote_legacy("rsi-threshold", parameters={"period": 21})
    assert [(c.rule_name, c.role) for c in promoted.components] == [
        ("rsi-threshold", "entry"),
        ("rsi-threshold", "exit"),
    ]
    assert all(c.parameters == {"period": 21} for c in promoted.components)


# --- serialisation ----------------------------------------------------------


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_every_template_round_trips_through_json(template_id):
    original = template(template_id)
    again = StrategySpec.from_dict(original.to_dict())
    assert again.to_dict() == original.to_dict()


def test_a_strategy_read_from_the_api_can_be_posted_straight_back():
    """Identity and timestamps belong to the store, not the spec."""
    payload = template("rsi-mean-reversion").to_dict()
    payload.update(
        {"id": "abc", "owner_id": "u1", "created_at": "now", "updated_at": "now"}
    )
    assert StrategySpec.from_dict(payload).name == "RSI mean reversion"


def test_an_unknown_top_level_field_is_refused():
    payload = template("rsi-mean-reversion").to_dict()
    payload["entry_logick"] = "any"
    with pytest.raises(StrategyValidationError, match="entry_logick"):
        StrategySpec.from_dict(payload)


# --- templates --------------------------------------------------------------


def _dated(bars, start="2020-01-01"):
    """The same path on real session dates, for rules that join other series."""
    from datetime import date, timedelta

    day = date.fromisoformat(start)
    out = []
    for bar in bars:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append(Bar(day.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume))
        day += timedelta(days=1)
    return out


def _ranging_path(seed: int, n: int = 400):
    """Mean-reverting around 100: the regime a reversion strategy is built for.

    The shared fixture drifts and trends; a gate that asks for "no trend" (ADX
    below 20) rightly never opens on it, which says nothing about whether the
    reversion template works where it should.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    level = 100.0
    out = []
    for i in range(n):
        level += 0.25 * (100.0 - level) + rng.normal(0, 1.6)
        high = level * (1 + abs(rng.normal(0, 0.008)))
        low = level * (1 - abs(rng.normal(0, 0.008)))
        open_ = float(min(max(level * (1 + rng.normal(0, 0.004)), low), high))
        out.append(Bar(f"d{i:04d}", open_, float(high), float(low), float(level), 1_000_000))
    return out


def _calm_vix(bars):
    return [Bar(b.date, 15.0, 15.0, 15.0, 15.0, 0) for b in bars]


def _healthy_facts(bars):
    """A profitable, cheap, growing company with cash-backed earnings.

    Annual filings, 60 days after each year end -- the basis the fundamental
    triggers compare. Revenue grows 12% a year and the operating margin widens
    two points a year, so revenue-growth and margin-expansion fire on the same
    filing date. P/E about 17, ROE 20%, margin from 14%, low leverage, and
    operating cash flow 50% above earnings keep every fundamental gate open.
    """
    from datetime import date, timedelta

    from quantlab.storage.facts import build_series

    first = date.fromisoformat(bars[0].date)
    rows = []
    for k, year in enumerate(range(first.year - 3, first.year + 3)):
        start = date(year, 1, 1).isoformat()
        end = date(year, 12, 31)
        filed = (end + timedelta(days=60)).isoformat()
        revenue = 5.0e9 * (1.12**k)
        rows += [
            {"concept": "net_income", "value": 6.0e8, "period_start": start,
             "period_end": end.isoformat(), "filed_at": filed},
            {"concept": "revenue", "value": revenue, "period_start": start,
             "period_end": end.isoformat(), "filed_at": filed},
            {"concept": "operating_income", "value": revenue * (0.14 + 0.02 * k),
             "period_start": start, "period_end": end.isoformat(), "filed_at": filed},
            {"concept": "operating_cash_flow", "value": 9.0e8, "period_start": start,
             "period_end": end.isoformat(), "filed_at": filed},
            {"concept": "shares_outstanding", "value": 1.0e8, "period_start": None,
             "period_end": end.isoformat(), "filed_at": filed},
            {"concept": "equity", "value": 3.0e9, "period_start": None,
             "period_end": end.isoformat(), "filed_at": filed},
            {"concept": "long_term_debt", "value": 3.0e8, "period_start": None,
             "period_end": end.isoformat(), "filed_at": filed},
        ]
    return build_series(rows)


def _inputs_for(template_id, series):
    """Each template on the data it declares it needs -- nothing more."""
    if template_id == "regime-reversion":
        return {s: _ranging_path(i + 5) for i, s in enumerate(series)}, {}, None
    if template_id == "macro-gated-trend":
        dated = {s: _dated(bars) for s, bars in series.items()}
        any_bars = next(iter(dated.values()))
        return dated, {}, {"VIX.FRED": _calm_vix(any_bars)}
    if template_id in {
        "quality-momentum",
        "test-candidate-systematic-3",
        "test-candidate-systematic-4",
    }:
        dated = {s: _dated(bars) for s, bars in series.items()}
        return dated, {s: _healthy_facts(bars) for s, bars in dated.items()}, None
    return series, {}, None


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_every_template_validates_and_actually_trades(template_id, series):
    spec_under_test = template(template_id)
    bars, facts, macro = _inputs_for(template_id, series)
    decisions, stats = compose(spec_under_test, bars, facts_by_symbol=facts, series=macro)
    assert stats.entry_decisions > 0, "a starter template that never enters is useless"

    result = simulate(list(bars), bars, decisions, spec_under_test.execution)
    assert result.trades, "a starter template must produce trades on a live-ish path"


def test_systematic_candidates_have_stable_identities_and_carver_risk_controls():
    expected = {f"test-candidate-systematic-{number}" for number in range(1, 5)}
    served = {item["id"]: item for item in catalogue() if item["id"].startswith("test-candidate")}
    assert set(served) == expected
    assert all(item["name"] == template_id for template_id, item in served.items())
    assert all(item["collection"] == "systematic-trading" for item in served.values())
    for item in served.values():
        assert item["execution"]["position_sizing"] == "volatility_target"

    for template_id in ("test-candidate-systematic-1", "test-candidate-systematic-2"):
        candidate = template(template_id)
        entries = [c for c in candidate.components if c.role == "entry"]
        assert [(c.parameters["fast"], c.parameters["slow"]) for c in entries] == [
            (8, 32),
            (16, 64),
            (32, 128),
        ]
        assert candidate.entry_logic == candidate.exit_logic == "majority"

    assert not template("test-candidate-systematic-1").execution.allow_shorts
    long_short = template("test-candidate-systematic-2").execution
    assert long_short.allow_shorts
    assert long_short.borrow_cost_bps == 50.0


def test_margin_expansion_fires_on_a_widening_margin(series):
    """It used to raise ValueError on every name with enough filings."""
    bars = _dated(series["AAA"])
    events = get_rule("margin-expansion").compute(bars, facts=_healthy_facts(bars), periods=2)
    assert events and all(e.direction == "bullish" for e in events)
    assert events[0].trigger_values["change"] > 0


def test_the_macro_gate_shuts_every_entry_in_a_crisis(series):
    """S6 against S1 on the same path: a VIX of 45 throughout leaves no entry."""
    dated = {s: _dated(bars) for s, bars in series.items()}
    any_bars = next(iter(dated.values()))
    panic = [Bar(b.date, 45.0, 45.0, 45.0, 45.0, 0) for b in any_bars]

    calm_vix = {"VIX.FRED": _calm_vix(any_bars)}
    _, calm = compose(template("macro-gated-trend"), dated, series=calm_vix)
    _, crisis = compose(template("macro-gated-trend"), dated, series={"VIX.FRED": panic})
    _, ungated = compose(template("regime-trend"), dated)

    assert calm.entry_decisions == ungated.entry_decisions > 0
    assert crisis.entry_decisions == 0


def test_the_macro_gate_without_its_series_stays_shut(series):
    """No VIX at all is not "calm": the gate emits nothing and stays shut."""
    dated = {s: _dated(bars) for s, bars in series.items()}
    _, stats = compose(template("macro-gated-trend"), dated)
    assert stats.entry_decisions == 0


def test_an_inverted_filter_stays_shut_while_its_indicator_warms_up(series):
    """The regression the S2 template depends on.

    An inverted ADX gate reads "no trend". Before ADX is defined it must stay
    shut -- flipping a warm-up "shut" into "open" would admit every early entry
    because the indicator had not been computed, not because it was low.
    """
    bars = {"AAA": _ranging_path(5)}
    gate = StrategyComponent(
        rule_name="adx-trend-filter", role="filter", parameters={"threshold": 20.0}, invert=True
    )
    entry = component("bollinger-reversion", "entry")
    decisions, _ = compose(spec(entry, gate), bars)
    adx_rule = get_rule("adx-trend-filter")
    first_defined = next(
        e.date for e in adx_rule.compute(bars["AAA"], period=14, threshold=20.0)
    )
    assert decisions, "the ranging path should produce some gated entries"
    assert all(d.date >= first_defined for d in decisions)


def test_every_template_charges_realistic_costs():
    """A template that shipped free would teach a new user that turnover is
    free, which is the most expensive lesson to unlearn."""
    for template_id in TEMPLATE_IDS:
        execution = template(template_id).execution
        assert execution.commission_bps > 0
        assert execution.slippage_bps > 0


def test_the_catalogue_serialises_every_template():
    served = catalogue()
    assert {item["id"] for item in served} == set(TEMPLATE_IDS)
    assert all(item["components"] for item in served)


def test_a_template_is_built_fresh_so_callers_cannot_mutate_the_catalogue():
    assert template("rsi-mean-reversion") is not template("rsi-mean-reversion")


# --- lookback ---------------------------------------------------------------


def test_lookback_is_the_deepest_component_plus_the_agreement_window():
    deep = get_rule("sma-crossover").lookback_days
    assert spec(component("sma-crossover", "entry")).lookback_days == deep
    assert (
        spec(component("sma-crossover", "entry"), combine_window_days=5).lookback_days
        == deep + 4
    )


def test_an_atr_stop_adds_its_own_warm_up():
    plain = spec(component("rsi-threshold", "entry"))
    with_atr = spec(
        component("rsi-threshold", "entry"),
        execution=ExecutionConfig(atr_stop_multiple=2.0, atr_period=20),
    )
    assert with_atr.lookback_days == plain.lookback_days + 21


# --- composition score (_score) ---------------------------------------------


def test_combine_scores_by_component_weight_for_every_logic():
    """Hand-calculated: score = active entry weight / total entry weight."""
    from quantlab.strategy.compose import _combine

    one = [object()]  # _combine only counts the firings
    two = [object(), object()]
    # all: 2 of 2 active, weights 1+1 -> eligible, 2/2.
    assert _combine(two, 2, [1.0, 1.0], "all", 0.0, 2.0) == (True, 1.0)
    # all: 1 of 2 active -> ineligible.
    assert _combine(one, 2, [1.0], "all", 0.0, 2.0)[0] is False
    # any: 1 of 4 equal weights -> 1/4.
    assert _combine(one, 4, [1.0], "any", 0.0, 4.0) == (True, 0.25)
    # majority: 2 of 3 equal -> 2/3.
    assert _combine(two, 3, [1.0, 1.0], "majority", 0.0, 3.0) == (True, 2 / 3)
    # majority still scores by weight, not count: (2+1)/(2+1+3).
    assert _combine(two, 3, [2.0, 1.0], "majority", 0.0, 6.0) == (True, 0.5)
    # weighted: weights 2,1,1; the 2 and one 1 active vs threshold 3 -> 3/4.
    assert _combine(two, 3, [2.0, 1.0], "weighted", 3.0, 4.0) == (True, 0.75)
    # weighted below threshold: no entry.
    assert _combine(one, 3, [1.0], "weighted", 3.0, 4.0)[0] is False
    # Nothing active: no entry.
    assert _combine([], 3, [], "any", 0.0, 3.0) == (False, 0.0)


def _entry_scores(strategy, series, weights):
    """Each entry/both decision's score next to the hand-calculated one.

    Entries use distinct rule names (and the exit a rule no entry uses), so
    the entry members are recoverable from ``_components`` by name.
    """
    decisions, _ = compose(strategy, series)
    total = sum(weights.values())
    out = []
    for item in decisions:
        if item.kind == "exit":
            continue
        names = item.trigger_values["_components"]
        expected = sum(weights[name] for name in names if name in weights) / total
        out.append((item.trigger_values["_score"], expected))
    return out


@pytest.mark.parametrize(
    ("logic", "threshold", "allowed"),
    [
        ("all", 1.0, {1.0}),
        ("any", 1.0, {1 / 4, 3 / 4, 1.0}),
        ("majority", 1.0, {1.0}),  # 2 entries: a majority needs both
        ("weighted", 3.0, {3 / 4, 1.0}),
    ],
)
def test_entry_score_is_the_active_share_of_entry_weight(series, logic, threshold, allowed):
    weights = {"rsi-threshold": 3.0, "macd-crossover": 1.0}
    strategy = spec(
        StrategyComponent("rsi-threshold", role="entry", weight=3.0),
        StrategyComponent("macd-crossover", role="entry", weight=1.0),
        StrategyComponent("breakout-20d", role="exit", weight=5.0),
        entry_logic=logic,
        entry_threshold=threshold,
        combine_window_days=5,
    )
    pairs = _entry_scores(strategy, series, weights)
    assert pairs
    for got, expected in pairs:
        assert got == pytest.approx(expected)
        assert any(got == pytest.approx(value) for value in allowed)


def test_a_single_component_and_a_promoted_legacy_run_score_one(series):
    for strategy in (
        spec(component("rsi-threshold", "entry"), component("macd-crossover", "exit")),
        promote_legacy("rsi-threshold"),
    ):
        decisions, _ = compose(strategy, series)
        scored = [d for d in decisions if d.kind != "exit"]
        assert scored and all(d.trigger_values["_score"] == 1.0 for d in scored)


def test_exit_only_decisions_carry_no_score(series):
    decisions, _ = compose(
        spec(component("rsi-threshold", "entry"), component("macd-crossover", "exit")),
        series,
    )
    exits = [d for d in decisions if d.kind == "exit"]
    assert exits and all("_score" not in d.trigger_values for d in exits)


def test_a_both_decision_scores_only_its_entry_members(series):
    """The heavy exit member fires on the same date, but only the entry side
    of the decision is conviction: active entries over 2 equal entries."""
    strategy = spec(
        StrategyComponent("rsi-threshold", role="entry"),
        StrategyComponent("macd-crossover", role="entry"),
        StrategyComponent("rsi-threshold", role="exit", weight=7.0),
        entry_logic="any",
        combine_window_days=1,
    )
    decisions, _ = compose(strategy, series)
    both = [d for d in decisions if d.kind == "both"]
    assert both
    for item in both:
        # Entry members first, then the single exit member.
        entry_names = item.trigger_values["_components"][:-1]
        assert item.trigger_values["_score"] == pytest.approx(len(entry_names) / 2)


def test_filters_never_count_toward_the_score(series):
    entries = (
        StrategyComponent("rsi-threshold", role="entry"),
        StrategyComponent("macd-crossover", role="entry"),
        StrategyComponent("breakout-20d", role="exit"),
    )
    plain = spec(*entries, entry_logic="any", combine_window_days=5)
    gated = spec(
        *entries,
        StrategyComponent(
            "adx-trend-filter", role="filter", weight=9.0, parameters={"threshold": 20.0}
        ),
        entry_logic="any",
        combine_window_days=5,
    )

    def scores(strategy):
        decisions, _ = compose(strategy, series)
        return {
            (d.symbol, d.date, d.direction): d.trigger_values["_score"]
            for d in decisions
            if d.kind != "exit"
        }

    plain_scores, gated_scores = scores(plain), scores(gated)
    assert gated_scores and set(gated_scores) <= set(plain_scores)
    assert all(gated_scores[key] == plain_scores[key] for key in gated_scores)


def test_contradictions_are_still_suppressed_with_scoring(series):
    contradiction = spec(
        StrategyComponent("rsi-threshold", role="entry"),
        StrategyComponent("rsi-threshold", role="entry", invert=True),
        entry_logic="any",
        combine_window_days=30,
    )
    decisions, stats = compose(contradiction, series)
    assert stats.contradictions > 0
    per_date: dict[tuple[str, str], set[str]] = {}
    for item in decisions:
        if item.kind in ("entry", "both"):
            assert 0.0 < item.trigger_values["_score"] <= 1.0
            per_date.setdefault((item.symbol, item.date), set()).add(item.direction)
    assert all(len(directions) == 1 for directions in per_date.values())


def test_scores_are_deterministic_and_survive_a_json_round_trip(series):
    import json

    first, _ = compose(template("dual-confirmation"), series)
    second, _ = compose(template("dual-confirmation"), series)
    assert [d.trigger_values for d in first] == [d.trigger_values for d in second]
    scored = [d for d in first if d.kind != "exit"]
    assert scored
    for item in scored:
        again = json.loads(json.dumps(item.trigger_values))
        assert again == item.trigger_values
        assert isinstance(again["_score"], float)


def test_an_old_spec_without_weights_scores_by_equal_weight(series):
    payload = {
        "name": "old",
        "components": [
            {"rule_name": "rsi-threshold", "role": "entry"},
            {"rule_name": "macd-crossover", "role": "entry"},
            {"rule_name": "breakout-20d", "role": "exit"},
        ],
        "entry_logic": "any",
        "combine_window_days": 5,
    }
    strategy = StrategySpec.from_dict(payload)
    assert all(c.weight == 1.0 for c in strategy.components)
    pairs = _entry_scores(strategy, series, {"rsi-threshold": 1.0, "macd-crossover": 1.0})
    assert pairs and all(got == pytest.approx(expected) for got, expected in pairs)
    assert {got for got, _ in pairs} <= {0.5, 1.0}
