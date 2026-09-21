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

import sqlite3
from pathlib import Path
from typing import Protocol

from quantlab.storage import db, facts, repository, warehouse


class StorageBackend(Protocol):
    """What a route is allowed to ask of storage."""

    name: str

    def health(self) -> tuple[bool, int]: ...
    def instrument_exists(self, symbol: str) -> bool: ...
    def list_instruments(self) -> dict: ...
    def get_prices(self, symbol: str, start: str | None, end: str | None) -> dict: ...
    def list_signals(self, **kwargs) -> dict: ...

    # What the experiment runner needs beyond serving the API (feature 006).
    # Callers pass the *warm-up* start, not the researcher's start.
    def load_bars_for(self, symbols: list[str], start: str, end: str) -> dict: ...
    def earliest_bar_dates(self, symbols: list[str]) -> dict: ...
    def corporate_actions(self, symbols: list[str], start: str, end: str) -> list[dict]: ...
    def instrument_ids(self, symbols: list[str]) -> dict: ...
    def ingest_run_ids(self, symbols: list[str], start: str, end: str) -> list: ...

    # Point-in-time fundamentals. Only the warehouse has any; the demo answers
    # empty rather than raising, and the rules then hold their gates shut --
    # the same shape every other warehouse-only seam here takes.
    def load_facts_for(
        self, symbols: list[str], concepts: list[str], start: str, end: str
    ) -> dict: ...
    def facts_as_of(
        self, symbol: str, as_of: str, concepts: list[str] | None = None
    ) -> list[dict]: ...


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

    def facts_as_of(
        self, symbol: str, as_of: str, concepts: list[str] | None = None
    ) -> list[dict]:
        return []


class WarehouseBackend:
    """Real ingested history: ClickHouse bars over a Postgres catalog."""

    name = "warehouse"

    def __init__(self, wh: warehouse.Warehouse | None = None) -> None:
        self.wh = wh or warehouse.Warehouse.from_env()

    def health(self) -> tuple[bool, int]:
        return warehouse.health(self.wh)

    def instrument_exists(self, symbol: str) -> bool:
        return warehouse.instrument_exists(self.wh, symbol)

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

    def instrument_ids(self, symbols: list[str]) -> dict[str, int]:
        return warehouse._instrument_ids(self.wh, symbols)

    def ingest_run_ids(self, symbols: list[str], start: str, end: str) -> list[int]:
        return warehouse.ingest_run_ids(self.wh, symbols, start, end)

    def load_facts_for(
        self, symbols: list[str], concepts: list[str], start: str, end: str
    ) -> dict[str, facts.FactSeries]:
        return warehouse.load_facts_for(self.wh, symbols, concepts, start, end)

    def facts_as_of(
        self, symbol: str, as_of: str, concepts: list[str] | None = None
    ) -> list[dict]:
        return warehouse.facts_as_of(self.wh, symbol, as_of, concepts)


def select_backend(db_path: str | Path | None = None) -> StorageBackend:
    """Pick the warehouse when it is configured, else the synthetic dataset."""
    if warehouse.configured():
        return WarehouseBackend()
    return SqliteBackend(db_path or "/data/quantlab.db")
