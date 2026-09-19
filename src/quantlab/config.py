"""Configuration: env vars, YAML pipelines, and on-disk layout."""
from __future__ import annotations

import dataclasses
import os
import pathlib
from typing import Any, Mapping

import yaml

DEFAULT_ROOT = pathlib.Path(os.environ.get("QUANTLAB_HOME", "~/.quantlab")).expanduser()


@dataclasses.dataclass
class Settings:
    root: pathlib.Path = DEFAULT_ROOT
    user_agent: str = dataclasses.field(
        default_factory=lambda: os.environ.get(
            "QUANTLAB_USER_AGENT",
            "quantlab/0.1 (research; set QUANTLAB_USER_AGENT to your name and email)",
        )
    )
    http_timeout: float = 30.0
    cache_ttl_seconds: int = 6 * 3600
    max_workers: int = 8
    offline: bool = dataclasses.field(
        default_factory=lambda: os.environ.get("QUANTLAB_OFFLINE", "") not in ("", "0", "false")
    )

    # API keys -- all optional, all free to obtain.
    fred_api_key: str = dataclasses.field(
        default_factory=lambda: os.environ.get("FRED_API_KEY", "")
    )
    openfigi_api_key: str = dataclasses.field(
        default_factory=lambda: os.environ.get("OPENFIGI_API_KEY", "")
    )
    companies_house_key: str = dataclasses.field(
        default_factory=lambda: os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    )

    @property
    def data_dir(self) -> pathlib.Path:
        return self._sub("data")

    @property
    def cache_dir(self) -> pathlib.Path:
        return self._sub("cache")

    @property
    def state_dir(self) -> pathlib.Path:
        return self._sub("state")

    @property
    def plugin_dir(self) -> pathlib.Path:
        return self._sub("plugins")

    def _sub(self, name: str) -> pathlib.Path:
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def sec_user_agent(self) -> str:
        """SEC requires a UA that identifies you with a contact address."""
        ua = os.environ.get("SEC_USER_AGENT") or self.user_agent
        if "@" not in ua:
            raise ValueError(
                "SEC EDGAR requires a User-Agent containing a contact email. "
                "Set SEC_USER_AGENT='Your Name your@email.com'."
            )
        return ua


_SETTINGS: Settings | None = None


def settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings()
    return _SETTINGS


def configure(**kwargs: Any) -> Settings:
    global _SETTINGS
    _SETTINGS = dataclasses.replace(settings(), **kwargs)
    return _SETTINGS


# ---------------------------------------------------------------------------
# Pipeline config
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class FeatureRequest:
    name: str
    params: dict[str, Any] = dataclasses.field(default_factory=dict)
    alias: str = ""

    @property
    def output_prefix(self) -> str:
        return self.alias or self.name

    @classmethod
    def parse(cls, item: Any) -> "FeatureRequest":
        """Accept 'rsi', {'rsi': {'period': 14}}, or a full dict form."""
        if isinstance(item, str):
            return cls(name=item)
        if isinstance(item, Mapping):
            if set(item) >= {"name"}:
                d = dict(item)
                return cls(
                    name=d.pop("name"),
                    alias=d.pop("as", "") or d.pop("alias", ""),
                    params=d.pop("params", None) or d,
                )
            if len(item) == 1:
                (name, params), = item.items()
                params = dict(params or {})
                return cls(name=name, alias=params.pop("as", ""), params=params)
        raise ValueError(f"cannot parse feature request: {item!r}")


@dataclasses.dataclass
class PipelineConfig:
    universe: str = "static"
    universe_params: dict[str, Any] = dataclasses.field(default_factory=dict)
    providers: list[str] = dataclasses.field(default_factory=lambda: ["stooq"])
    provider_options: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    start: str = "2015-01-01"
    end: str = ""
    frequency: str = "1d"
    features: list[FeatureRequest] = dataclasses.field(default_factory=list)
    price_column: str = "adj_close"
    normalise_currency: bool = True
    output: str = ""
    max_workers: int = 8

    @classmethod
    def from_yaml(cls, path: str | pathlib.Path) -> "PipelineConfig":
        raw = yaml.safe_load(pathlib.Path(path).expanduser().read_text()) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PipelineConfig":
        raw = dict(raw)
        uni = raw.pop("universe", "static")
        uni_params: dict[str, Any] = dict(raw.pop("universe_params", {}) or {})
        if isinstance(uni, Mapping):
            if "name" in uni:
                d = dict(uni)
                name = d.pop("name")
                uni_params.update(d)
                uni = name
            elif len(uni) == 1:
                (name, params), = uni.items()
                uni_params.update(dict(params or {}))
                uni = name
        providers = raw.pop("providers", None) or [raw.pop("provider", "stooq")]
        if isinstance(providers, str):
            providers = [providers]
        feats = [FeatureRequest.parse(f) for f in (raw.pop("features", []) or [])]
        known = {f.name for f in dataclasses.fields(cls)}
        extra = {k: v for k, v in raw.items() if k in known}
        return cls(
            universe=str(uni), universe_params=uni_params, providers=list(providers),
            features=feats, **extra,
        )
