"""live-ingest: IBKR prices for leased symbols, to Kafka and ClickHouse.

Pure parts (symbol mapping, the line plan, minute rolling, trading hours) are
modules of their own and tested without IBKR; ``collector`` wires them to the
adapters in ``ib``, ``store`` and ``bus``.
"""
