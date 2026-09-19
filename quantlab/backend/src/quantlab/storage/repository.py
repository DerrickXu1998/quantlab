"""Repository: persistence helpers for the seed pipeline and read queries for
the API. All functions take an open sqlite3 connection; writers do NOT commit
(the caller owns the transaction) so seeding can run as one atomic replace.
"""

from __future__ import annotations

import json
import sqlite3

from quantlab import config
from quantlab.signals.engine import ComputedSignal
from quantlab.signals.registry import SignalRule
from quantlab.storage import db
from quantlab.storage.db import (
    InstrumentRow,
    PriceBarRow,
    SignalRow,
    SignalRuleRow,
    canonical_json,
)
from quantlab.synthetic.generator import Bar

# ---------------------------------------------------------------------------
# Writes (seed pipeline)
# ---------------------------------------------------------------------------


def upsert_instruments(conn: sqlite3.Connection) -> int:
    rows = [
        InstrumentRow(
            symbol=spec.symbol,
            name=spec.name,
            currency=config.CURRENCY,
            regime_profile=spec.regime_profile,
            seed=config.instrument_seed(spec.symbol),
        )
        for spec in config.UNIVERSE
    ]
    db.upsert_instruments(conn, rows)
    return len(rows)


def insert_bars(conn: sqlite3.Connection, bars_by_symbol: dict[str, list[Bar]]) -> int:
    rows = [
        PriceBarRow(symbol, bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume)
        for symbol in sorted(bars_by_symbol)
        for bar in bars_by_symbol[symbol]
    ]
    db.upsert_price_bars(conn, rows)
    return len(rows)


def mirror_rules(conn: sqlite3.Connection, rules: list[SignalRule]) -> int:
    """Snapshot the registered rules into signal_rules (registry is authoritative)."""
    rows = [
        SignalRuleRow(
            rule_name=rule.name,
            rule_version=rule.version,
            parameters=canonical_json(rule.params),
            lookback_days=rule.lookback_days,
            scale_class=rule.scale_class,
            direction_semantics=rule.direction_semantics,
        )
        for rule in rules
    ]
    db.upsert_signal_rules(conn, rows)
    return len(rows)


def insert_signals(conn: sqlite3.Connection, signals: list[ComputedSignal]) -> int:
    rows = [
        SignalRow(
            symbol=s.symbol,
            date=s.date,
            rule_name=s.rule_name,
            rule_version=s.rule_version,
            parameters=canonical_json(s.parameters),
            direction=s.direction,
            trigger_values=canonical_json(s.trigger_values),
            data_window_end=s.data_window_end,
        )
        for s in signals
    ]
    db.upsert_signals(conn, rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Reads (API + tests)
# ---------------------------------------------------------------------------


def is_seeded(conn: sqlite3.Connection) -> bool:
    return db.get_meta(conn, "seeded") == "1"


def signal_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM signals").fetchone()[0]


def instrument_exists(conn: sqlite3.Connection, symbol: str) -> bool:
    row = conn.execute("SELECT 1 FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    return row is not None


def list_instruments(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT i.symbol, i.name, i.currency, i.regime_profile,
               (SELECT count(*) FROM price_bars p WHERE p.symbol = i.symbol) AS bar_count,
               (SELECT count(*) FROM signals s WHERE s.symbol = i.symbol) AS signal_count
        FROM instruments i
        ORDER BY i.symbol
        """
    ).fetchall()
    items = [
        {
            "symbol": symbol,
            "name": name,
            "currency": currency,
            "regime_profile": regime_profile,
            "bar_count": bar_count,
            "signal_count": sig_count,
        }
        for symbol, name, currency, regime_profile, bar_count, sig_count in rows
    ]
    return {"total": len(items), "items": items}


def get_prices(
    conn: sqlite3.Connection,
    symbol: str,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    where = ["symbol = ?"]
    params: list = [symbol]
    if start is not None:
        where.append("date >= ?")
        params.append(start)
    if end is not None:
        where.append("date <= ?")
        params.append(end)
    rows = conn.execute(
        f"SELECT symbol, date, open, high, low, close, volume FROM price_bars "
        f"WHERE {' AND '.join(where)} ORDER BY date ASC",
        params,
    ).fetchall()
    items = [
        {
            "symbol": s,
            "date": d,
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": v,
        }
        for s, d, o, h, lo, c, v in rows
    ]
    return {"total": len(items), "items": items}


def list_signals(
    conn: sqlite3.Connection,
    *,
    instrument: str | None = None,
    signal_type: str | None = None,
    direction: str | None = None,
    start: str | None = None,
    end: str | None = None,
    sort: str = "date_desc",
    limit: int = 200,
    offset: int = 0,
) -> dict:
    where: list[str] = []
    params: list = []
    if instrument is not None:
        where.append("symbol = ?")
        params.append(instrument)
    if signal_type is not None:
        where.append("rule_name = ?")
        params.append(signal_type)
    if direction is not None:
        where.append("direction = ?")
        params.append(direction)
    if start is not None:
        where.append("date >= ?")
        params.append(start)
    if end is not None:
        where.append("date <= ?")
        params.append(end)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(f"SELECT count(*) FROM signals {where_sql}", params).fetchone()[0]
    order = "ASC" if sort == "date_asc" else "DESC"
    rows = conn.execute(
        f"""
        SELECT id, symbol, date, rule_name, rule_version, parameters, direction,
               trigger_values, data_window_end
        FROM signals {where_sql}
        ORDER BY date {order}, id {order}
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    items = [
        {
            "id": row_id,
            "symbol": symbol,
            "date": date,
            "rule_name": rule_name,
            "rule_version": rule_version,
            "parameters": json.loads(parameters),
            "direction": direction_,
            "trigger_values": json.loads(trigger_values),
            "data_window_end": data_window_end,
        }
        for (
            row_id,
            symbol,
            date,
            rule_name,
            rule_version,
            parameters,
            direction_,
            trigger_values,
            data_window_end,
        ) in rows
    ]
    return {"total": total, "items": items}


def load_all_bars(conn: sqlite3.Connection) -> dict[str, list[Bar]]:
    """Load every stored price bar as Bar objects (used by re-derivation tests)."""
    rows = conn.execute(
        "SELECT symbol, date, open, high, low, close, volume FROM price_bars ORDER BY symbol, date"
    ).fetchall()
    bars_by_symbol: dict[str, list[Bar]] = {}
    for symbol, date, open_, high, low, close, volume in rows:
        bars_by_symbol.setdefault(symbol, []).append(Bar(date, open_, high, low, close, volume))
    return bars_by_symbol
