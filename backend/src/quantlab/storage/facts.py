"""Point-in-time fundamentals: the value a fact *had* on a trading date.

This module is the whole feature, and it exists because the obvious query is
wrong in a way that flatters the result. ``fundamentals`` holds one row per
(fact, filing), so a single number appears many times: every 10-K restates its
comparatives. Joining on ``period_end`` picks an arbitrary one of those rows,
and if it picks the newest, a backtest has traded 2024 on a document filed in
2026. The mistake makes a strategy look *better*, which is why it survives.

Measured against the live warehouse on 2026-09-21, Caterpillar on 2024-06-30:

  * the rule below returns revenue 15,799,000,000, period ending 2024-03-31,
    filed 2024-05-01 -- 60 days stale, and genuinely the best anyone had;
  * a ``period_end <= as_of`` join returns 16,689,000,000 for the quarter
    ending 2024-06-30, from a filing dated **2026-03-26**.

The rule (docs/FUNDAMENTALS.md §2)
----------------------------------

For an as-of date ``D``, consider only rows with ``filed_at <= D``. Within each
``(instrument_id, concept)`` take the greatest ``period_end``, breaking ties on
the greatest ``filed_at``. Forward-fill that value until a later filing
supersedes it.

Three consequences, all load-bearing:

1. timing comes from ``filed_at``, never ``period_end``;
2. a restatement supersedes from its own filing date forward, never backwards;
3. the first weeks of a period correctly carry the *previous* period's figure.

The negative-lag rows (710 of them, ``filed_at < period_end``) need no special
case: the rule keys on ``filed_at``, so a row filed on 2021-08-09 is knowable
from 2021-08-09 whatever period label it carries.

What §2 leaves underdetermined, and this module fixes
-----------------------------------------------------

Measured on the same warehouse, 42,276 groups share one
``(instrument, concept, period_end, filed_at)`` and disagree on ``value``. Two
distinct causes, and picking arbitrarily between them is not a rounding error:

**Period length.** Apple's Q2-2012 revenue is filed as both 39,186,000,000
(the three months) and 85,519,000,000 (the six months to the same date) on the
same day. Flow concepts are period-to-date at many filers -- Apple's recent
revenue runs 90, 181, 272 then 363 days -- so "the latest revenue" alternates
between a quarter and a year and a naive YoY comparison is meaningless. Facts
are therefore bucketed by :data:`SCOPES` and a rule asks for the bucket it can
actually use: an instant for a balance-sheet stock, an annual period for a
flow. Nothing here silently mixes the two.

**Tag choice.** One concept maps from several raw XBRL tags, and a filing can
carry more than one of them (``Revenues`` and
``RevenueFromContractWithCustomerIncludingAssessedTax`` differing by 38k).
:data:`TAG_PREFERENCE` ports the ingest side's fallback chain so the *same* tag
wins every time -- determinism (Constitution VI) plus the preference the
ingester itself would have expressed.

No pandas: the backend serves JSON and a per-symbol step list of a few dozen
entries is cheaper to binary-search than to frame.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------

#: Balance-sheet concepts: a level at an instant, filed with no ``period_start``.
#: Verified against the warehouse -- ``equity`` has 84,836 rows and 84,836 of
#: them are instants.
INSTANT_CONCEPTS: frozenset[str] = frozenset(
    {
        "total_assets",
        "total_liabilities",
        "equity",
        "current_assets",
        "current_liabilities",
        "cash",
        "long_term_debt",
        "shares_outstanding",
        "net_short_position",
    }
)

#: Income-statement and cash-flow concepts: a quantity accumulated *over* a
#: period, so the period's length is part of the number's meaning.
FLOW_CONCEPTS: frozenset[str] = frozenset(
    {
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "capex",
        "short_volume",
        "short_exempt_volume",
        "total_volume",
    }
)

#: Every concept a rule may ask for.
KNOWN_CONCEPTS: frozenset[str] = INSTANT_CONCEPTS | FLOW_CONCEPTS

#: FINRA daily short volume begins 2026-08-20 and UK FCA disclosure covers 77
#: names. Rules built on these would match nothing over a historical window,
#: so no rule ships against them yet (docs/FUNDAMENTALS.md §5.2).
SHORT_INTEREST_CONCEPTS: frozenset[str] = frozenset(
    {"net_short_position", "short_volume", "short_exempt_volume", "total_volume"}
)

#: Which raw XBRL tag wins when a filing carries two that map to one concept.
#: Ported from ``quantlab.providers.sec_edgar.CONCEPT_TAGS`` and
#: ``providers.companies_house.UK_TAGS`` -- ported, not imported: ``backend/``
#: and ``src/`` are separate distributions that are never installed together
#: (docs/ARCHITECTURE.md). Earlier in a list is preferred.
TAG_PREFERENCE: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_income": ("OperatingIncomeLoss",),
    "gross_profit": ("GrossProfit",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "shares_outstanding": (
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ),
}

#: A tag not in the chain (Companies House, or a tag added since) sorts after
#: every tag that is, and alphabetically among its peers -- deterministic
#: without pretending to a preference nobody expressed.
_UNRANKED = 10_000

_TAG_RANK: dict[tuple[str, str], int] = {
    (concept, tag): rank
    for concept, tags in TAG_PREFERENCE.items()
    for rank, tag in enumerate(tags)
}


def tag_rank(concept: str, tag: str) -> int:
    return _TAG_RANK.get((concept, tag), _UNRANKED)


# ---------------------------------------------------------------------------
# Period scope
# ---------------------------------------------------------------------------

#: How long a fact's period is. A flow figure is only comparable with another
#: of the same scope, and mixing them is the difference between a P/E of 12 and
#: one of 48.
SCOPES: tuple[str, ...] = ("instant", "quarter", "interim", "annual")

#: Upper bounds, in days, for the duration buckets. Fiscal quarters run 89-92
#: days and fiscal years 363-371, so the boundaries sit in the empty space
#: between the clusters rather than on top of one.
_QUARTER_MAX_DAYS = 130
_INTERIM_MAX_DAYS = 300


def scope_of(period_start: str | None, period_end: str) -> str:
    """Which duration bucket a filed period falls in."""
    if not period_start:
        return "instant"
    days = _days_between(period_start, period_end)
    if days <= _QUARTER_MAX_DAYS:
        return "quarter"
    if days <= _INTERIM_MAX_DAYS:
        return "interim"
    return "annual"


def default_scope(concept: str) -> str:
    """The bucket a rule gets when it does not name one.

    A stock has only an instant. A flow defaults to the annual figure: it is
    the one every filer publishes on the same basis, so a ratio built from it
    means the same thing across the selection. A quarterly default would
    compare a period-to-date filer's Q3 against a discrete-quarter filer's,
    which is a 3x error wearing the same units.
    """
    return "instant" if concept in INSTANT_CONCEPTS else "annual"


def _days_between(start: str, end: str) -> int:
    """Whole days between two ISO dates, without importing datetime per call."""
    from datetime import date

    return (date.fromisoformat(end) - date.fromisoformat(start)).days


# ---------------------------------------------------------------------------
# One fact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """One filed number, with everything needed to judge whether to trust it."""

    concept: str
    value: float
    period_start: str | None
    period_end: str
    filed_at: str
    scope: str = "instant"
    tag: str = ""

    @property
    def period_days(self) -> int | None:
        if not self.period_start:
            return None
        return _days_between(self.period_start, self.period_end)

    def days_stale(self, as_of: str) -> int:
        """How long this number had been public on ``as_of``.

        Staleness is measured from the filing, not the period end. A figure
        describing last December that was filed yesterday is one day old as
        information, however old the accounting period is.
        """
        return _days_between(self.filed_at, as_of)

    def forward_dated(self) -> bool:
        """``filed_at < period_end``: a filing carrying a forward period label.

        710 rows in the warehouse (0.012%), genuine SEC tagging oddities. Not
        dropped -- dropping data because it looks strange is how a dataset ends
        up clean and wrong -- but surfaced so the inspector can flag it.
        """
        return self.filed_at < self.period_end

    def to_dict(self, as_of: str) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "value": self.value,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "filed_at": self.filed_at,
            "scope": self.scope,
            "days_stale": self.days_stale(as_of),
            "forward_dated": self.forward_dated(),
        }


def _selection_key(row: Fact) -> tuple:
    """Total order over candidate rows; the greatest wins on a given date.

    ``(period_end, filed_at)`` is the rule from §2. The rest only ever breaks a
    tie §2 does not reach, and exists so the same inputs always choose the same
    row (Constitution VI):

      * ``period_start`` descending -- prefer the shorter, more discrete period
        when one filing tags both a quarter and the year-to-date ending on the
        same day. Within a scope this almost never fires; across scopes it is
        what stops a 6-month figure masquerading as a 3-month one.
      * tag rank -- the ingest side's own fallback chain.
      * value -- last resort, so even two identically-tagged dimensional
        duplicates resolve the same way every time.
    """
    return (
        row.period_end,
        row.filed_at,
        row.period_start or "",
        -tag_rank(row.concept, row.tag),
        row.value,
    )


# ---------------------------------------------------------------------------
# The per-symbol series
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chain:
    """A superseding sequence of facts, searchable by date.

    ``dates`` is kept beside ``facts`` rather than zipped into it so a bisect
    compares strings. Zipping would make the comparison fall through to
    :class:`Fact`, which is unordered on purpose -- there is no single "greater"
    fact, only a greater one under :func:`_selection_key`.
    """

    dates: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)

    def at(self, on: str) -> Fact | None:
        """The last fact filed on or before ``on``. The forward-fill."""
        index = bisect_right(self.dates, on) - 1
        return self.facts[index] if index >= 0 else None

    def append(self, filed_at: str, fact: Fact) -> None:
        self.dates.append(filed_at)
        self.facts.append(fact)

    def __bool__(self) -> bool:
        return bool(self.facts)


@dataclass(frozen=True)
class FactSeries:
    """One instrument's facts, answerable as of any date.

    Stored as *step points* rather than a value per trading day. A name filing
    quarterly for seventeen years has around seventy steps per concept, so the
    whole series is a few hundred entries and an as-of read is a binary search.
    Materialising a row per (date, concept) instead would be five million dicts
    for a forty-name run and would answer no question faster.

    Two views over the same rows, because rules need both:

      * :meth:`value` -- the §2 answer within one duration scope, forward-filled.
        What a filter reads.
      * :meth:`history` -- the sequence of *distinct periods* known on a date,
        each at its latest-filed value. What a change signal reads, because
        "revenue grew" is a statement about two periods, not two dates.
    """

    #: (concept, scope) -> the superseding chain. Only steps that actually
    #: change the answer are kept.
    steps: dict[tuple[str, str], Chain] = field(default_factory=dict)
    #: (concept, scope) -> period_end -> every filed version of that period,
    #: which is what makes a restatement visible rather than merely applied.
    versions: dict[tuple[str, str], dict[str, Chain]] = field(default_factory=dict)
    #: The ingest runs these rows came from (docs/FUNDAMENTALS.md §5.3).
    #: Carried on the series rather than fetched separately so the lineage
    #: cannot drift from the data it explains, and so reading facts stays one
    #: query per run.
    run_ids: tuple[int, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.steps)

    @property
    def concepts(self) -> list[str]:
        return sorted({concept for concept, _ in self.steps})

    def has(self, concept: str, scope: str | None = None) -> bool:
        return bool(self.steps.get((concept, scope or default_scope(concept))))

    def value(
        self,
        concept: str,
        on: str,
        *,
        scope: str | None = None,
        max_stale_days: int | None = None,
    ) -> Fact | None:
        """The §2 answer for ``concept`` on date ``on``, or None.

        None means *unknown*, and every caller must treat it as unknown rather
        than as zero: a name with no filed ``equity`` has no book value, so P/B
        is undefined and its gate is shut. Reading the absence as zero would
        make it read as cheap (docs/FUNDAMENTALS.md §5.5).

        ``max_stale_days`` shuts the gate on a figure nobody would still quote.
        A company that stopped filing in 2019 should not be gating a 2024 trade
        on its last balance sheet, and without a bound the forward-fill happily
        carries it forever.
        """
        chain = self.steps.get((concept, scope or default_scope(concept)))
        if chain is None:
            return None
        fact = chain.at(on)
        if fact is None:
            return None
        if max_stale_days is not None and fact.days_stale(on) > max_stale_days:
            return None
        return fact

    def history(
        self,
        concept: str,
        on: str,
        *,
        scope: str | None = None,
        limit: int | None = None,
    ) -> list[Fact]:
        """Distinct periods known on ``on``, oldest first, each latest-filed.

        This is the point-in-time *panel* a change signal needs. Year-on-year
        growth compares two periods, and comparing two dates instead would call
        an ordinary restatement a change in the business.

        A period appears only once its first filing has landed, and carries
        whatever the most recent filing on or before ``on`` says -- so a
        restatement rewrites history from its own filing date forward and never
        before it.
        """
        by_period = self.versions.get((concept, scope or default_scope(concept)))
        if not by_period:
            return []
        out: list[Fact] = []
        for period_end in sorted(by_period):
            fact = by_period[period_end].at(on)
            if fact is not None:
                out.append(fact)
        return out[-limit:] if limit else out

    def as_of(self, on: str, *, concepts: list[str] | None = None) -> list[Fact]:
        """Every concept's latest known fact on ``on``, for the inspector.

        Uses the plain §2 rule across all scopes -- "what did I know" is a
        question about the filings, not about which bucket a rule would pick.
        """
        wanted = sorted(set(concepts) & set(self.concepts)) if concepts else self.concepts
        out: list[Fact] = []
        for concept in wanted:
            candidates = [
                fact
                for scope in SCOPES
                if (fact := self.value(concept, on, scope=scope)) is not None
            ]
            if candidates:
                out.append(max(candidates, key=_selection_key))
        return out


#: A backend with no fundamentals returns this rather than raising. The demo
#: has none at all, and a rule must degrade to a shut gate, not to an error
#: (docs/FUNDAMENTALS.md §5.5).
EMPTY = FactSeries()


def build_series(rows: list[dict[str, Any]]) -> FactSeries:
    """Turn one instrument's raw fundamentals rows into a :class:`FactSeries`.

    Pure, so the point-in-time rule is testable from fixtures with no database
    anywhere near it. ``rows`` need not be sorted and may contain every
    restatement of every period; that is what they are for.

    The walk is the rule stated once: bucket by duration, order by filing date,
    and keep a running best under :func:`_selection_key`. A row whose
    ``period_end`` is behind the running best is a comparative -- a 10-K
    repeating last year -- and correctly changes nothing about "the latest
    figure", while still being recorded as a new version of *its own* period so
    :meth:`FactSeries.history` sees the restatement.
    """
    facts: list[Fact] = []
    run_ids: set[int] = set()
    for row in rows:
        if row.get("run_id") is not None:
            run_ids.add(int(row["run_id"]))
        period_start = _iso(row.get("period_start"))
        period_end = _iso(row["period_end"])
        if period_end is None:
            continue
        facts.append(
            Fact(
                concept=str(row["concept"]),
                value=float(row["value"]),
                period_start=period_start,
                period_end=period_end,
                filed_at=_iso(row["filed_at"]) or period_end,
                scope=scope_of(period_start, period_end),
                tag=str(row.get("tag") or ""),
            )
        )

    # Pass 1: every filed version of every period, one entry per filing date.
    # Two rows filed the same day for the same period are the tag-choice
    # collision -- 42,276 groups in the warehouse -- and _selection_key, not
    # row order, decides between them.
    grouped: dict[tuple[str, str], dict[str, dict[str, Fact]]] = {}
    for fact in facts:
        per_day = grouped.setdefault((fact.concept, fact.scope), {}).setdefault(
            fact.period_end, {}
        )
        current = per_day.get(fact.filed_at)
        if current is None or _selection_key(fact) > _selection_key(current):
            per_day[fact.filed_at] = fact

    versions: dict[tuple[str, str], dict[str, Chain]] = {}
    for key, by_period in grouped.items():
        versions[key] = {
            period_end: _chain_of(per_day) for period_end, per_day in by_period.items()
        }

    # Pass 2: the superseding chain. At each filing date, re-ask the rule over
    # every period known by then and keep the winner -- which is the greatest
    # period_end, so a comparative restating an older period changes nothing.
    steps: dict[tuple[str, str], Chain] = {}
    for key, by_period in versions.items():
        filing_dates = sorted({date for chain in by_period.values() for date in chain.dates})
        out = Chain()
        for filed_at in filing_dates:
            best: Fact | None = None
            for chain in by_period.values():
                candidate = chain.at(filed_at)
                if candidate is None:
                    continue
                if best is None or _selection_key(candidate) > _selection_key(best):
                    best = candidate
            if best is None:  # pragma: no cover - a filing date implies a fact
                continue
            if out.facts and out.facts[-1] == best:
                continue  # nothing the rule can see actually changed
            out.append(filed_at, best)
        if out:
            steps[key] = out

    return FactSeries(steps=steps, versions=versions, run_ids=tuple(sorted(run_ids)))


def _chain_of(per_day: dict[str, Fact]) -> Chain:
    chain = Chain()
    for filed_at in sorted(per_day):
        chain.append(filed_at, per_day[filed_at])
    return chain


def _iso(value: Any) -> str | None:
    """Accept a date, a datetime or an ISO string; return YYYY-MM-DD."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value[:10]
    return value.isoformat()[:10]


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactCoverage:
    """Who in a selection can actually trade a fundamental rule.

    docs/FUNDAMENTALS.md §5.1: a strategy with a fundamental filter over names
    that have no fundamentals does not "find no trades", it *cannot* trade, and
    a result cannot tell the two apart. So the run says which it was.
    """

    concepts: list[str]
    instruments_requested: int
    instruments_with_facts: int
    instruments_missing: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concepts": list(self.concepts),
            "instruments_requested": self.instruments_requested,
            "instruments_with_facts": self.instruments_with_facts,
            "instruments_missing": list(self.instruments_missing),
        }


def coverage_of(
    facts_by_symbol: dict[str, FactSeries], symbols: list[str], concepts: list[str]
) -> FactCoverage:
    """Which requested instruments have every concept the strategy needs.

    "Has every concept" rather than "has any": a P/E filter needs net income
    *and* shares outstanding, and a name with one of the two is exactly as
    untradeable as a name with neither.
    """
    wanted = sorted(set(concepts))
    missing = [
        symbol
        for symbol in symbols
        if not all(
            (series := facts_by_symbol.get(symbol)) is not None and series.has(concept)
            for concept in wanted
        )
    ]
    return FactCoverage(
        concepts=wanted,
        instruments_requested=len(symbols),
        instruments_with_facts=len(symbols) - len(missing),
        instruments_missing=missing,
    )
