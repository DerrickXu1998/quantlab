"""Canonical quantlab symbols -> IBKR stock symbols.

quantlab names a US listing ``AAPL.US``; IBKR wants ``AAPL`` on SMART in USD,
and writes share classes with a space (``BRK B``) where vendors use a dot or a
dash (``BRK.B``, ``BRK-B``). Anything that is not a US listing has no mapping
here -- the line budget is for the S&P, and a guessed foreign contract is
worse than an honest ``unknown_symbol``.
"""

from __future__ import annotations

import re

US_SUFFIX = ".US"
_ROOT = re.compile(r"^[A-Z][A-Z0-9]*([.\-][A-Z])?$")


def ib_symbol(canonical: str) -> str | None:
    """``BRK.B.US`` -> ``BRK B``; None when there is no US mapping."""
    if not canonical.endswith(US_SUFFIX):
        return None
    root = canonical[: -len(US_SUFFIX)]
    if not _ROOT.match(root):
        return None
    return re.sub(r"[.\-]", " ", root)
