"""Universe sources: where the list of companies comes from."""
from __future__ import annotations

_REGISTERED = False


def register_all() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    from . import lse, nasdaqtrader, static  # noqa: F401

    _REGISTERED = True


register_all()
