"""Read path: ClickHouse bars + Postgres catalog, stitched into one panel.

`load_panel` is the mirror of `quantlab.data.load` -- same (date, symbol) long
panel, same columns -- so modelling code does not care whether the bars came
off the wire or out of the warehouse.

The join between the two stores happens here, in Python, on instrument_id.
That is the price of the split: ClickHouse holds no symbols and Postgres holds
no bars. In exchange the bar table scans at columnar speed and identity keeps
its constraints.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Sequence

import pandas as pd

from ..engine import Context
from . import bars as bars_mod
from . import catalog

log = logging.getLogger(__name__)

_PANEL_COLUMNS = ("open", "high", "low", "close", "volume", "adj_close")


def load_panel(
    conn,
    client,
    symbols: Sequence[str] | None = None,
    *,
    start: str | dt.date | None = None,
    end: str | dt.date | None = None,
    frequency: str = "1d",
    universe_snapshot: int | None = None,
    return_context: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, Context]:
    """Load a long (date, symbol) panel out of the store.

    Passing `universe_snapshot` restricts the panel to the members of that
    snapshot, which is how a point-in-time backtest avoids survivorship bias:
    model the universe as it was, not as it survived.
    """
    if universe_snapshot is not None:
        wanted_ids = catalog.snapshot_members(conn, universe_snapshot)
        id_to_symbol = catalog.symbols_for_ids(conn, wanted_ids)
        if symbols:
            keep = set(symbols)
            id_to_symbol = {k: v for k, v in id_to_symbol.items() if v in keep}
    else:
        resolved = catalog.instrument_ids(conn, list(symbols)) if symbols else {}
        if symbols and not resolved:
            id_to_symbol = {}
        elif symbols:
            id_to_symbol = {v: k for k, v in resolved.items()}
        else:
            all_symbols = catalog.list_symbols(conn)
            resolved = catalog.instrument_ids(conn, all_symbols)
            id_to_symbol = {v: k for k, v in resolved.items()}

    if not id_to_symbol:
        panel = _empty_panel()
        return (panel, Context(frequency=frequency)) if return_context else panel

    frame = bars_mod.load_bars(
        client,
        list(id_to_symbol),
        start=start,
        end=end,
        frequency=frequency,
    )

    if frame is None or frame.empty:
        panel = _empty_panel()
    else:
        frame = frame.copy()
        frame["symbol"] = frame["instrument_id"].map(id_to_symbol)
        frame["date"] = pd.to_datetime(frame["ts"])
        for column in _PANEL_COLUMNS:
            if column not in frame.columns:
                frame[column] = pd.NA
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        panel = (
            frame[["date", "symbol", *_PANEL_COLUMNS]]
            .set_index(["date", "symbol"])
            .sort_index()
        )

    if not return_context:
        return panel

    present = sorted(panel.index.get_level_values("symbol").unique().tolist())
    securities = catalog.load_securities(conn, present)
    context = Context(
        securities=securities,
        currencies={s: sec.currency for s, sec in securities.items()},
        frequency=frequency,
        extras={"origin": "clickhouse", "universe_snapshot": universe_snapshot},
    )
    return panel, context


def _empty_panel() -> pd.DataFrame:
    return pd.DataFrame(
        columns=list(_PANEL_COLUMNS),
        index=pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([], name="date"), pd.Index([], name="symbol", dtype=object)]
        ),
    )


def coverage(conn, client, frequency: str = "1d") -> pd.DataFrame:
    """Per-symbol coverage summary, joining ClickHouse counts to catalog names.

    The first thing to look at after an ingest, and the cheapest way to spot a
    provider that silently started returning short history.
    """
    frame = bars_mod.coverage(client, frequency=frequency)
    if frame is None or frame.empty:
        return pd.DataFrame(
            columns=["symbol", "bars", "first_ts", "last_ts", "sources"]
        )

    id_to_symbol = catalog.symbols_for_ids(conn, frame["instrument_id"].tolist())
    frame["symbol"] = frame["instrument_id"].map(id_to_symbol)
    frame["sources"] = frame["sources"].map(
        lambda v: ",".join(sorted(v)) if isinstance(v, (list, tuple)) else v
    )
    return (
        frame[["symbol", "bars", "first_ts", "last_ts", "sources"]]
        .sort_values("symbol")
        .reset_index(drop=True)
    )


def panel_for_modelling(
    conn,
    client,
    symbols: Sequence[str] | None = None,
    *,
    start: str | dt.date | None = None,
    end: str | dt.date | None = None,
    frequency: str = "1d",
    universe_snapshot: int | None = None,
    out: str = "",
) -> str:
    """Materialise a panel to Parquet for the feature engine.

    ClickHouse is fast enough to model against directly, but a pinned Parquet
    file is reproducible in a way a live query is not: it is the artefact a
    backtest result can be traced back to.
    """
    from ..data import save_panel

    panel = load_panel(
        conn,
        client,
        symbols,
        start=start,
        end=end,
        frequency=frequency,
        universe_snapshot=universe_snapshot,
    )
    return save_panel(panel, out)
