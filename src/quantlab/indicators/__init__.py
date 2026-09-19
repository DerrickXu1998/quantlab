"""Built-in technical indicators.

Importing this module registers every builtin. Third-party packages can add
more via the ``quantlab.indicators`` entry-point group, or by calling
``quantlab.registry.indicator`` at import time.
"""
from __future__ import annotations

_REGISTERED = False


def register_all() -> None:
    """Import every builtin indicator module exactly once."""
    global _REGISTERED
    if _REGISTERED:
        return
    from . import momentum, statistics, trend, volatility, volume  # noqa: F401

    _REGISTERED = True


register_all()
