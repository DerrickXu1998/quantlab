"""Built-in derived / alternative-data features.

Split by what they need:

* **Panel-only** (``cross_sectional``, ``regime``, ``seasonality``) -- work
  offline from the price panel you already have. Zero marginal cost.
* **Externally sourced** (``shorts``, ``insider``, ``fundamentals``,
  ``macro``) -- fetch from a free official source through a provider. They
  degrade to NaN with a warning rather than failing the whole run, so a
  pipeline keeps working when one source is down.
"""
from __future__ import annotations

_REGISTERED = False


def register_all() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    from . import (  # noqa: F401
        cross_sectional,
        fundamentals,
        insider,
        macro,
        regime,
        seasonality,
        shorts,
    )

    _REGISTERED = True


register_all()
