"""The quantlab warehouse schema.

Every Postgres and ClickHouse migration the application's data lives in, and
the runner that applies them (`quantlab migrate`, run by the `migrate` step of
every deploy before the backend starts). Nothing here loads data: ingestion,
providers and the research library live in quantlab-data-pipeline, which keeps
pinned copies of these migrations and never changes the schema itself.

The application is in backend/ (its own `quantlab` package, in its own image).
"""

__version__ = "0.2.0"
