"""A user's settings: one validated document, read and changed as a whole.

Everything a person configures about QuantLab for themselves, kept with their
account rather than in one browser: the theme, the Market tab's default data
mode and saved ticker lists, and the IBKR login (username and account type)
they use for live prices.

What is deliberately *not* here: the IBKR password. Live prices come from the
user's own IBKR account, and the password is handed to their own gateway and
stored nowhere (see quantlab.streaming.live_manager); the settings only
remember which login to offer next time.

Changes are JSON merge patches (RFC 7386): objects merge, anything else --
including lists -- replaces, and ``null`` puts a key back to its default.
Unknown keys are refused, so a typo is a 422 rather than a setting that is
silently saved and never read.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._\-]{0,19}$")
MAX_LISTS = 50
MAX_LIST_SYMBOLS = 200


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppearanceSettings(_Strict):
    #: The terminal is dark by design; light is an explicit choice.
    theme: Literal["dark", "light"] = "dark"


class SavedList(_Strict):
    name: str = Field(min_length=1, max_length=60)
    symbols: list[str] = Field(default_factory=list, max_length=MAX_LIST_SYMBOLS)

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for symbol in value:
            if not SYMBOL.match(symbol):
                raise ValueError(f"not a symbol: {symbol!r}")
            if symbol not in out:
                out.append(symbol)
        return out


class MarketSettings(_Strict):
    #: What the Market tab opens on when a link does not say.
    default_data: Literal["historical", "live"] = "historical"
    #: Ticker lists the user saved in the Market tab.
    lists: list[SavedList] = Field(default_factory=list, max_length=MAX_LISTS)

    @field_validator("lists")
    @classmethod
    def _unique_names(cls, value: list[SavedList]) -> list[SavedList]:
        names = [item.name for item in value]
        if len(names) != len(set(names)):
            raise ValueError("list names must be unique")
        return value


class IbkrSettings(_Strict):
    #: The IBKR login offered when connecting. Never the password.
    username: str | None = Field(default=None, min_length=1, max_length=64)
    trading_mode: Literal["paper", "live"] = "paper"


class UserSettings(_Strict):
    appearance: AppearanceSettings = Field(default_factory=AppearanceSettings)
    market: MarketSettings = Field(default_factory=MarketSettings)
    ibkr: IbkrSettings = Field(default_factory=IbkrSettings)


def defaults() -> dict:
    return UserSettings().model_dump()


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386: objects merge recursively, ``null`` deletes, the rest replaces."""
    if not isinstance(patch, dict):
        return patch
    out = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = merge_patch(out.get(key), value)
    return out


def apply(current: dict, patch: dict) -> dict:
    """``current`` changed by ``patch``, validated; raises pydantic.ValidationError."""
    return UserSettings.model_validate(merge_patch(current, patch)).model_dump()


def load(stored: dict | None) -> dict:
    """A stored document, re-validated; a key this version no longer knows is
    dropped rather than failing the user's whole settings."""
    if not stored:
        return defaults()
    known = UserSettings.model_fields
    try:
        return UserSettings.model_validate(
            {k: v for k, v in stored.items() if k in known}
        ).model_dump()
    except ValueError:
        return defaults()
