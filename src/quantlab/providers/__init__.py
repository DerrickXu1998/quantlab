"""Built-in data providers.

Imported one at a time on purpose: a missing optional dependency (yfinance,
openpyxl) must degrade to "that provider is unavailable", never to "the
registry failed to load".
"""
from __future__ import annotations

import importlib
import logging

log = logging.getLogger(__name__)

_MODULES = ("csvfile", "stooq", "sec_edgar", "companies_house", "boe", "fred", "openfigi", "yahoo", "finra", "fca")
_REGISTERED = False


def register_all() -> None:
    """Entry point target. Idempotent."""
    global _REGISTERED
    if _REGISTERED:
        return
    for mod in _MODULES:
        try:
            importlib.import_module(f".{mod}", __name__)
        except Exception as exc:  # pragma: no cover - depends on optional deps
            log.debug("provider %s not available: %s", mod, exc)
    _REGISTERED = True


register_all()
