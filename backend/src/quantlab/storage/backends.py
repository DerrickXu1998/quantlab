"""Storage backend selection.

Two datasets, one API:

  * **warehouse** -- real ingested history. ClickHouse bars over a Postgres
    catalog. Active when QUANTLAB_DB_URL and QUANTLAB_CH_URL are both set.
  * **sqlite** -- the synthetic demo dataset. No network, no databases, fully
    deterministic. The fallback, and what `make demo` runs.

Routes talk to whichever backend is bound to ``app.state.backend`` and never
branch on which one it is.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Protocol

from quantlab.storage import db, facts, repository, warehouse

#: The demo's large-run lock (see SqliteBackend.large_run_slot).
_DEMO_LARGE_RUN = threading.Lock()


class StorageBackend(Protocol):
    """What a route is allowed to ask of storage."""

    name: str

    def health(self) -> tuple[bool, int]: ...
    def instrument_exists(self, symbol: str) -> bool: ...
    def validate_symbols(self, symbols: list[str]) -> list[str]: ...
    def list_instruments(self) -> dict: ...
    def get_prices(self, symbol: str, start: str | None, end: str | None) -> dict: ...
    def list_signals(self, **kwargs) -> dict: ...

    # What the experiment runner needs beyond serving the API (feature 006).
    # Callers pass the *warm-up* start, not the researcher's start.
    def load_bars_for(self, symbols: list[str], start: str, end: str) -> dict: ...
    def earliest_bar_dates(self, symbols: list[str]) -> dict: ...
    def corporate_actions(self, symbols: list[str], start: str, end: str) -> list[dict]: ...
    #: Hold "a large backtest is running" for the block; yields whether it
    #: was acquired within ``timeout`` seconds. Server-wide on the warehouse.
    def large_run_slot(self, timeout: float) -> AbstractContextManager[bool]: ...
    #: Intraday signal bars (5m/15m/1h) as BarSeries; empty where there are none.
    def load_intraday_bars(
        self, symbols: list[str], start: str, end: str, frequency: str
    ) -> dict: ...
    #: {session date: minute bars} for one symbol; empty where the store has none.
    def minute_bars(self, symbol: str, start: str, end: str) -> dict: ...
    def instrument_ids(self, symbols: list[str]) -> dict: ...
    def ingest_run_ids(self, symbols: list[str], start: str, end: str) -> list: ...

    # Point-in-time fundamentals. Only the warehouse has any; the demo answers
    # empty rather than raising, and the rules then hold their gates shut --
    # the same shape every other warehouse-only seam here takes.
    def load_facts_for(
        self, symbols: list[str], concepts: list[str], start: str, end: str
    ) -> dict: ...
    #: The first date every concept has a filing for some symbol; None if any
    #: concept has none (or the store holds no fundamentals at all).
    def fundamentals_start(
        self, symbols: list[str], concepts: list[str], end: str
    ) -> str | None: ...
    def facts_as_of(
        self, symbol: str, as_of: str, concepts: list[str] | None = None
    ) -> list[dict]: ...

    # What the research destination needs (docs/RESEARCH.md). Every one of
    # these is answerable on both stores: the demo has no fundamentals and no
    # universe history, so it answers zero and empty rather than raising, for
    # the same reason `load_facts_for` does.
    def fundamentals_coverage(self) -> dict: ...
    def list_universes(self) -> dict: ...
    def publish_universe(
        self, name: str, symbols: list[str], snapshot_date: str | None = None
    ) -> dict: ...
    def ensure_default_universe(self) -> None: ...
    def universe_members(self, name: str, as_of: str) -> dict | None: ...
    def company_overview(self, symbol: str, as_of: str) -> dict | None: ...
    def screen(self, **kwargs) -> dict | None: ...


class SqliteBackend:
    """Synthetic demo dataset in a local SQLite file."""

    name = "sqlite"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    def _seeded_conn(self) -> sqlite3.Connection | None:
        if not Path(self.db_path).is_file():
            return None
        try:
            conn = db.connect(self.db_path)
        except sqlite3.OperationalError:
            return None
        return conn

    def health(self) -> tuple[bool, int]:
        conn = self._seeded_conn()
        if conn is None:
            return False, 0
        try:
            if repository.is_seeded(conn):
                return True, repository.signal_count(conn)
            return False, 0
        except sqlite3.OperationalError:
            return False, 0  # file exists but schema missing -> unseeded
        finally:
            conn.close()

    def instrument_exists(self, symbol: str) -> bool:
        with db.connect(self.db_path) as conn:
            return repository.instrument_exists(conn, symbol)

    def validate_symbols(self, symbols: list[str]) -> list[str]:
        with db.connect(self.db_path) as conn:
            return repository.validate_symbols(conn, symbols)

    def list_instruments(self) -> dict:
        with db.connect(self.db_path) as conn:
            return repository.list_instruments(conn)

    def get_prices(self, symbol: str, start: str | None, end: str | None) -> dict:
        with db.connect(self.db_path) as conn:
            return repository.get_prices(conn, symbol, start=start, end=end)

    def list_signals(self, **kwargs) -> dict:
        with db.connect(self.db_path) as conn:
            return repository.list_signals(conn, **kwargs)

    def load_bars_for(self, symbols: list[str], start: str, end: str) -> dict:
        with db.connect(self.db_path) as conn:
            return repository.load_bars_for(conn, symbols, start, end)

    def earliest_bar_dates(self, symbols: list[str]) -> dict:
        with db.connect(self.db_path) as conn:
            return repository.earliest_bar_dates(conn, symbols)

    def corporate_actions(self, symbols: list[str], start: str, end: str) -> list[dict]:
        # The synthetic dataset has none. Answering rather than raising is what
        # keeps the runner free of branching on which store it is talking to.
        return []

    @contextmanager
    def large_run_slot(self, timeout: float) -> Iterator[bool]:
        # One process serves the demo, so a process-wide lock is server-wide.
        acquired = _DEMO_LARGE_RUN.acquire(timeout=timeout)
        try:
            yield acquired
        finally:
            if acquired:
                _DEMO_LARGE_RUN.release()

    def load_intraday_bars(
        self, symbols: list[str], start: str, end: str, frequency: str
    ) -> dict:
        # The demo is daily only; the runner refuses an intraday run on it
        # rather than reporting an empty one.
        return {}

    def minute_bars(self, symbol: str, start: str, end: str) -> dict:
        # No minute bars in the demo: a minute-resolution run falls back to
        # the daily rule session by session, and says how often it did.
        return {}

    def instrument_ids(self, symbols: list[str]) -> dict[str, int]:
        # The demo has no surrogate identities; symbols are its identity.
        return {}

    def ingest_run_ids(self, symbols: list[str], start: str, end: str) -> list[int]:
        # The demo's data is seeded deterministically, not ingested, so there
        # is no ingest lineage to record.
        return []

    def load_facts_for(
        self, symbols: list[str], concepts: list[str], start: str, end: str
    ) -> dict[str, facts.FactSeries]:
        """None. The synthetic universe has prices and nothing else.

        Empty rather than an exception, for the same reason
        :meth:`corporate_actions` answers ``[]``: the runner must not branch on
        which store it is talking to. Every fundamental rule then sees no
        facts, and a rule that sees no facts holds its gate shut and emits no
        entry -- so a demo strategy with a P/E filter simply never trades,
        which is the truth, rather than trading on a P/E of zero
        (docs/FUNDAMENTALS.md §5.5).
        """
        return {}

    def fundamentals_start(
        self, symbols: list[str], concepts: list[str], end: str
    ) -> str | None:
        # No filings, so no start to limit a window to; the runner's demo
        # refusal is what names the problem.
        return None

    def facts_as_of(
        self, symbol: str, as_of: str, concepts: list[str] | None = None
    ) -> list[dict]:
        return []

    def fundamentals_coverage(self) -> dict:
        """Every instrument, none of them covered.

        The instrument total is the real one rather than a zero: "12 names, 0
        with filings" is the truth about the demo and is the shape the coverage
        warning is built to read. Zeroing the total too would say the catalogue
        is empty, which it is not.
        """
        instruments = [item["symbol"] for item in self.list_instruments()["items"]]
        return {
            "instruments_total": len(instruments),
            "instruments_with_facts": 0,
            "concepts": [],
            "symbols_with_facts": [],
            "symbols_without_facts": instruments,
        }

    def list_universes(self) -> dict:
        # The synthetic dataset is one flat list with no membership history.
        return {"total": 0, "items": []}

    def publish_universe(
        self, name: str, symbols: list[str], snapshot_date: str | None = None
    ) -> dict:
        raise NotImplementedError("the demo dataset has no universe history")

    def ensure_default_universe(self) -> None:
        pass

    def universe_members(self, name: str, as_of: str) -> dict | None:
        # No universe history, so no universe to resolve.
        return None

    def company_overview(self, symbol: str, as_of: str) -> dict | None:
        """The same page, minus the half the demo has no data for.

        Composed from the repository reads the routes already use rather than
        from fresh SQL, so the demo cannot drift from what `/instruments` and
        `/signals` answer about the same name.
        """
        with db.connect(self.db_path) as conn:
            instrument = next(
                (
                    item
                    for item in repository.list_instruments(conn)["items"]
                    if item["symbol"] == symbol
                ),
                None,
            )
            if instrument is None:
                return None
            bars = repository.get_prices(conn, symbol)["items"]
            signals = repository.list_signals(
                conn, instrument=symbol, limit=max(instrument["signal_count"], 1)
            )["items"]

        quoted = [bar for bar in bars if bar["date"] <= as_of]
        by_rule: dict[str, dict] = {}
        for signal in signals:
            entry = by_rule.setdefault(
                signal["rule_name"],
                {"rule_name": signal["rule_name"], "count": 0, "last_date": None,
                 "last_direction": None},
            )
            entry["count"] += 1
            if entry["last_date"] is None or signal["date"] > entry["last_date"]:
                entry["last_date"] = signal["date"]
                entry["last_direction"] = signal["direction"]

        return {
            "symbol": symbol,
            "name": instrument["name"],
            # The demo has no venue and no sector. Blank is what the warehouse
            # returns for 607 of its 644 names too, so the page renders the
            # same way rather than growing a second empty state.
            "exchange": "",
            "currency": instrument["currency"],
            "sector": "",
            "as_of": as_of,
            "first_bar": bars[0]["date"] if bars else None,
            "last_bar": bars[-1]["date"] if bars else None,
            "last_close": quoted[-1]["close"] if quoted else None,
            "facts": [],
            "concepts_available": [],
            # Everything is missing, and that is the honest answer: the demo
            # has filed nothing, so no concept is merely stale here.
            "concepts_missing": sorted(facts.KNOWN_CONCEPTS),
            "signals": sorted(
                by_rule.values(), key=lambda item: (-item["count"], item["rule_name"])
            ),
            "signal_total": sum(item["count"] for item in by_rule.values()),
        }

    def screen(
        self,
        *,
        universe: str,
        as_of: str,
        metrics: list[str],
        constraints=(),
        sort_by: str | None = None,
        descending: bool = False,
        limit: int = 100,
        **_: object,
    ) -> dict:
        """An empty screen, never an error.

        No fundamentals means no metric is measurable, so every name is
        unmeasured rather than excluded -- and the coverage rows say so by
        reporting 0 of 0 measured against the concepts each metric would have
        needed. A 404 here would claim the universe was misspelled.
        """
        return {
            "as_of": as_of,
            "universe": universe,
            "universe_size": 0,
            "rows": [],
            "coverage": [
                {
                    "metric": metric,
                    "measured": 0,
                    "universe": 0,
                    "requires": list(warehouse.SCREEN_METRIC_CONCEPTS[metric]),
                }
                for metric in warehouse.SCREEN_METRICS
                if metric in set(metrics)
            ],
            "sort_by": sort_by,
            "excluded_by_constraint": 0,
            "excluded_unmeasured": 0,
        }


class WarehouseBackend:
    """Real ingested history: ClickHouse bars over a Postgres catalog."""

    name = "warehouse"

    def __init__(self, wh: warehouse.Warehouse | None = None) -> None:
        self.wh = wh or warehouse.Warehouse.from_env()

    def health(self) -> tuple[bool, int]:
        return warehouse.health(self.wh)

    def instrument_exists(self, symbol: str) -> bool:
        return warehouse.instrument_exists(self.wh, symbol)

    def validate_symbols(self, symbols: list[str]) -> list[str]:
        return warehouse.validate_symbols(self.wh, symbols)

    def list_instruments(self) -> dict:
        return warehouse.list_instruments(self.wh)

    def get_prices(self, symbol: str, start: str | None, end: str | None) -> dict:
        return warehouse.get_prices(self.wh, symbol, start=start, end=end)

    def list_signals(self, **kwargs) -> dict:
        return warehouse.list_signals(self.wh, **kwargs)

    def load_bars_for(self, symbols: list[str], start: str, end: str) -> dict:
        return warehouse.load_bars_for(self.wh, symbols, start, end)

    def earliest_bar_dates(self, symbols: list[str]) -> dict:
        return warehouse.earliest_bar_dates(self.wh, symbols)

    def corporate_actions(self, symbols: list[str], start: str, end: str) -> list[dict]:
        return warehouse.corporate_actions(self.wh, symbols, start, end)

    def large_run_slot(self, timeout: float) -> AbstractContextManager[bool]:
        return warehouse.large_run_slot(self.wh, timeout)

    def load_daily_columns(self, symbols: list[str], start: str, end: str) -> dict:
        return warehouse.load_daily_columns(self.wh, symbols, start, end)

    def load_intraday_bars(
        self, symbols: list[str], start: str, end: str, frequency: str
    ) -> dict:
        return warehouse.load_intraday_bars(self.wh, symbols, start, end, frequency)

    def minute_bars(self, symbol: str, start: str, end: str) -> dict:
        # A run reads many months of the same few symbols: resolve each id
        # once rather than paying a catalog round trip per month.
        ids = self.__dict__.setdefault("_minute_ids", {})
        if symbol not in ids:
            ids[symbol] = warehouse._instrument_ids(self.wh, [symbol]).get(symbol)
        if ids[symbol] is None:
            return {}
        return warehouse.minute_bars(self.wh, symbol, start, end, ids[symbol])

    def instrument_ids(self, symbols: list[str]) -> dict[str, int]:
        return warehouse._instrument_ids(self.wh, symbols)

    def ingest_run_ids(self, symbols: list[str], start: str, end: str) -> list[int]:
        return warehouse.ingest_run_ids(self.wh, symbols, start, end)

    def load_facts_for(
        self, symbols: list[str], concepts: list[str], start: str, end: str
    ) -> dict[str, facts.FactSeries]:
        return warehouse.load_facts_for(self.wh, symbols, concepts, start, end)

    def fundamentals_start(
        self, symbols: list[str], concepts: list[str], end: str
    ) -> str | None:
        return warehouse.fundamentals_start(self.wh, symbols, concepts, end)

    def facts_as_of(
        self, symbol: str, as_of: str, concepts: list[str] | None = None
    ) -> list[dict]:
        return warehouse.facts_as_of(self.wh, symbol, as_of, concepts)

    def fundamentals_coverage(self) -> dict:
        return warehouse.fundamentals_coverage(self.wh)

    def list_universes(self) -> dict:
        return warehouse.list_universes(self.wh)

    def publish_universe(
        self, name: str, symbols: list[str], snapshot_date: str | None = None
    ) -> dict:
        date: dt.date | None = None
        if snapshot_date:
            date = dt.date.fromisoformat(snapshot_date)
        return warehouse.publish_universe(self.wh, name, symbols, snapshot_date=date)

    def ensure_default_universe(self) -> None:
        warehouse.ensure_default_universe(self.wh)

    def universe_members(self, name: str, as_of: str) -> dict | None:
        snapshot = warehouse.resolve_universe(self.wh, name, as_of)
        if snapshot is None:
            return None
        return {"name": snapshot.universe, "as_of": snapshot.as_of, "symbols": snapshot.symbols}

    def company_overview(self, symbol: str, as_of: str) -> dict | None:
        return warehouse.company_overview(self.wh, symbol, as_of)

    def screen(self, **kwargs) -> dict | None:
        return warehouse.screen(self.wh, **kwargs)


def select_backend(db_path: str | Path | None = None) -> StorageBackend:
    """Pick the warehouse when it is configured, else the synthetic dataset."""
    if warehouse.configured():
        return WarehouseBackend()
    return SqliteBackend(db_path or "/data/quantlab.db")
