"""Connections to the two halves of the store.

    QUANTLAB_DB_URL  -> Postgres catalog (identity, provenance, universe)
    QUANTLAB_CH_URL  -> ClickHouse bars   (price history)

Both default to the local Docker Compose stack, so the same code runs on a
laptop, in the stack, and in tests against throwaway databases.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, Iterator
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_DSN = "postgresql://quantlab:quantlab@localhost:5432/quantlab"
DEFAULT_CH_URL = "clickhouse://quantlab:quantlab@localhost:8123/quantlab"

ENV_VAR = "QUANTLAB_DB_URL"
CH_ENV_VAR = "QUANTLAB_CH_URL"
#: The ClickHouse password when the URL carries none (a managed service's
#: secret kept out of the address). Postgres has libpq's own PGPASSWORD.
CH_PASSWORD_ENV = "QUANTLAB_CH_PASSWORD"


class StoreNotConfigured(RuntimeError):
    """A required driver or connection string is missing."""


# ---------------------------------------------------------------------------
# Postgres (catalog)
# ---------------------------------------------------------------------------


def dsn(explicit: str = "") -> str:
    """Resolve the Postgres connection string: explicit > environment > default."""
    return explicit or os.environ.get(ENV_VAR) or DEFAULT_DSN


def _psycopg():
    try:
        import psycopg
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise StoreNotConfigured(
            "psycopg is not installed. Install the Postgres extra:\n"
            "    pip install 'quantlab[postgres]'"
        ) from exc
    return psycopg


def connect(url: str = "", *, autocommit: bool = False, **kwargs: Any):
    """Open a psycopg3 connection to the catalog.

    Callers own the transaction. Catalog writers never commit on their own so
    a whole catalog update lands atomically.
    """
    psycopg = _psycopg()
    return psycopg.connect(dsn(url), autocommit=autocommit, **kwargs)


@contextlib.contextmanager
def session(url: str = "", **kwargs: Any) -> Iterator[Any]:
    """Context manager yielding a catalog connection, committing on clean exit."""
    conn = connect(url, **kwargs)
    try:
        yield conn
        if not conn.autocommit:
            conn.commit()
    except BaseException:
        if not conn.autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def ping(url: str = "") -> bool:
    """Cheap catalog reachability check."""
    try:
        with session(url, autocommit=True) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# ClickHouse (bars)
# ---------------------------------------------------------------------------


def ch_url(explicit: str = "") -> str:
    """Resolve the ClickHouse URL: explicit > environment > default."""
    return explicit or os.environ.get(CH_ENV_VAR) or DEFAULT_CH_URL


def _parse_ch_url(url: str) -> dict[str, Any]:
    """clickhouse[s]://user:pass@host:port/db -> clickhouse_connect kwargs.

    `clickhouses://` (or `?secure=true`) is TLS, defaulting to 8443 -- what a
    managed ClickHouse Cloud service speaks.
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    secure = parsed.scheme in ("clickhouses", "https") or query.get("secure", [""])[0].lower() in (
        "1",
        "true",
        "yes",
    )
    # Percent-decoded: a managed service's generated password routinely holds
    # `@`, `/` or `%`, which only survive a URL encoded -- and urlparse hands
    # them back still encoded. With no password in the URL at all, it comes
    # from QUANTLAB_CH_PASSWORD, so the secret can live apart from the address.
    password = unquote(parsed.password) if parsed.password else os.environ.get(CH_PASSWORD_ENV, "")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or (8443 if secure else 8123),
        "username": unquote(parsed.username) if parsed.username else "default",
        "password": password,
        "database": (parsed.path or "/default").lstrip("/") or "default",
        "secure": secure,
    }


def ch_connect(url: str = "", **kwargs: Any):
    """Open a ClickHouse client.

    Note there is no transaction to own: ClickHouse inserts are atomic per
    block and nothing more. Cross-system consistency is handled in
    `quantlab.store.ingest` by ordering the writes and recording truth in the
    Postgres ingest_runs row.
    """
    try:
        import clickhouse_connect
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise StoreNotConfigured(
            "clickhouse-connect is not installed. Install the ClickHouse extra:\n"
            "    pip install 'quantlab[clickhouse]'"
        ) from exc

    settings = _parse_ch_url(ch_url(url))
    settings.update(kwargs)
    database = settings.pop("database")

    # Connect without a database first so migrations can create it.
    client = clickhouse_connect.get_client(**settings)
    client.command(f"CREATE DATABASE IF NOT EXISTS {database}")
    client.close()

    return clickhouse_connect.get_client(database=database, **settings)


@contextlib.contextmanager
def ch_session(url: str = "", **kwargs: Any) -> Iterator[Any]:
    """Context manager yielding a ClickHouse client, closed on exit."""
    client = ch_connect(url, **kwargs)
    try:
        yield client
    finally:
        client.close()


def ch_ping(url: str = "") -> bool:
    """Cheap ClickHouse reachability check."""
    try:
        with ch_session(url) as client:
            client.command("SELECT 1")
        return True
    except Exception:
        return False
