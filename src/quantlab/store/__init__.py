"""The warehouse schema and the runner that applies it.

Two stores, split by the shape of the data (docs/STORAGE.md): ClickHouse holds
`price_bars`; Postgres holds the catalog -- instruments, symbol maps, universes,
ingest runs, corporate actions, fundamentals, signals, experiment runs,
strategies and accounts. Their migrations are the files in `migrations/`
(Postgres) and `ch_migrations/` (ClickHouse), applied in filename order and
recorded with a checksum in each store's `schema_migrations`.

To change the schema, add the next numbered file; never edit an applied one
(the runner refuses, with MigrationDrift). quantlab-data-pipeline keeps pinned
copies of these files (`make sync-schema` there) and loads data into them.
"""

from __future__ import annotations

from .conn import (
    CH_ENV_VAR,
    DEFAULT_CH_URL,
    DEFAULT_DSN,
    ENV_VAR,
    StoreNotConfigured,
    ch_connect,
    ch_ping,
    ch_session,
    ch_url,
    connect,
    dsn,
    ping,
    session,
)
from .migrate import (
    CH_MIGRATIONS_DIR,
    MIGRATIONS_DIR,
    MigrationDrift,
    ch_current_version,
    ch_migrate,
    current_version,
    migrate,
    migrate_all,
)

__all__ = [
    "CH_ENV_VAR",
    "CH_MIGRATIONS_DIR",
    "DEFAULT_CH_URL",
    "DEFAULT_DSN",
    "ENV_VAR",
    "MIGRATIONS_DIR",
    "MigrationDrift",
    "StoreNotConfigured",
    "ch_connect",
    "ch_current_version",
    "ch_migrate",
    "ch_ping",
    "ch_session",
    "ch_url",
    "connect",
    "current_version",
    "dsn",
    "migrate",
    "migrate_all",
    "ping",
    "session",
]
