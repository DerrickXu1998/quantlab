"""The plugin system.

Three ways to add capability to quantlab, in increasing order of formality:

1. **Decorator, in-process** -- call ``@indicator(...)`` / ``@derived(...)`` in
   any module you import. Good for notebooks and one-offs.
2. **Plugin directory** -- drop a ``.py`` file in ``~/.quantlab/plugins`` (or any
   path in ``QUANTLAB_PLUGIN_PATH``). Loaded at startup, no packaging needed.
3. **Entry points** -- ship a real distribution advertising
   ``quantlab.providers`` / ``quantlab.indicators`` / ``quantlab.derived`` /
   ``quantlab.universes``. ``pip install`` is the whole install step.

All three land in the same registries, so a builtin and a third-party feature
are indistinguishable to the engine.
"""
from __future__ import annotations

import dataclasses
import importlib
import importlib.metadata
import importlib.util
import logging
import os
import pathlib
import sys
import threading
from typing import Any, Callable, Generic, Iterator, TypeVar

from .schema import FeatureSpec

log = logging.getLogger(__name__)

T = TypeVar("T")

ENTRY_POINT_GROUPS = {
    "providers": "quantlab.providers",
    "universes": "quantlab.universes",
    "indicators": "quantlab.indicators",
    "derived": "quantlab.derived",
}


class DuplicatePlugin(RuntimeError):
    pass


class PluginNotFound(KeyError):
    def __init__(self, kind: str, name: str, available: list[str]):
        self.kind, self.name = kind, name
        hint = ", ".join(sorted(available)) or "<none registered>"
        super().__init__(f"unknown {kind} {name!r}. Available: {hint}")


class Registry(Generic[T]):
    """A namespaced, thread-safe, override-aware plugin table."""

    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, T] = {}
        self._origin: dict[str, str] = {}
        self._lock = threading.RLock()

    def register(self, name: str, obj: T, *, origin: str = "runtime", override: bool = False) -> T:
        key = name.strip().lower()
        with self._lock:
            if key in self._items and not override:
                prev = self._origin.get(key, "?")
                raise DuplicatePlugin(
                    f"{self.kind} {key!r} already registered by {prev}; "
                    f"pass override=True to replace it"
                )
            self._items[key] = obj
            self._origin[key] = origin
        return obj

    def get(self, name: str) -> T:
        key = name.strip().lower()
        with self._lock:
            if key not in self._items:
                raise PluginNotFound(self.kind, name, list(self._items))
            return self._items[key]

    def maybe(self, name: str) -> T | None:
        return self._items.get(name.strip().lower())

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._items)

    def origin(self, name: str) -> str:
        return self._origin.get(name.strip().lower(), "?")

    def items(self) -> Iterator[tuple[str, T]]:
        with self._lock:
            yield from sorted(self._items.items())

    def unregister(self, name: str) -> None:
        with self._lock:
            self._items.pop(name.strip().lower(), None)
            self._origin.pop(name.strip().lower(), None)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.strip().lower() in self._items

    def __len__(self) -> int:
        return len(self._items)


# ---------------------------------------------------------------------------
# Feature plugins (indicators + derived data)
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True, slots=True)
class FeaturePlugin:
    """A callable plus the metadata the engine needs to schedule it.

    ``fn`` signature depends on ``spec.cross_sectional``:
      * False -> ``fn(df: DataFrame, **params) -> Series | DataFrame``
        where ``df`` is a single symbol's bars, time-indexed.
      * True  -> ``fn(panel: DataFrame, ctx: Context, **params) -> DataFrame``
        where ``panel`` is the long (date, symbol) panel.
    """

    spec: FeatureSpec
    fn: Callable[..., Any]

    @property
    def name(self) -> str:
        return self.spec.name


PROVIDERS: Registry[Any] = Registry("provider")
UNIVERSES: Registry[Any] = Registry("universe")
INDICATORS: Registry[FeaturePlugin] = Registry("indicator")
DERIVED: Registry[FeaturePlugin] = Registry("derived feature")


def _feature_decorator(
    registry: Registry[FeaturePlugin],
    kind: str,
    name: str,
    **spec_kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        spec = FeatureSpec(
            name=name,
            kind=kind,
            description=spec_kwargs.pop("description", None) or (fn.__doc__ or "").strip(),
            **spec_kwargs,
        )
        origin = spec_kwargs.pop("origin", None) or getattr(fn, "__module__", "runtime")
        registry.register(
            name, FeaturePlugin(spec=spec, fn=fn),
            origin=origin, override=bool(spec_kwargs.get("override")),
        )
        fn.quantlab_spec = spec  # type: ignore[attr-defined]
        return fn

    return wrap


def indicator(name: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a per-symbol technical indicator."""
    override = kwargs.pop("override", False)
    dec = _feature_decorator(INDICATORS, "indicator", name, **kwargs)

    def wrap(fn):
        if override:
            INDICATORS.unregister(name)
        return dec(fn)

    return wrap


def derived(name: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a derived / alternative-data feature."""
    override = kwargs.pop("override", False)
    dec = _feature_decorator(DERIVED, "derived", name, **kwargs)

    def wrap(fn):
        if override:
            DERIVED.unregister(name)
        return dec(fn)

    return wrap


def provider(name: str, *, override: bool = False) -> Callable[[type], type]:
    def wrap(cls: type) -> type:
        PROVIDERS.register(name, cls, origin=cls.__module__, override=override)
        return cls

    return wrap


def universe(name: str, *, override: bool = False) -> Callable[[type], type]:
    def wrap(cls: type) -> type:
        UNIVERSES.register(name, cls, origin=cls.__module__, override=override)
        return cls

    return wrap


def lookup_feature(name: str) -> FeaturePlugin:
    """Find a feature in either registry; indicators win ties."""
    found = INDICATORS.maybe(name) or DERIVED.maybe(name)
    if found is None:
        raise PluginNotFound("feature", name, INDICATORS.names() + DERIVED.names())
    return found


def all_features() -> dict[str, FeaturePlugin]:
    out: dict[str, FeaturePlugin] = {}
    for _, p in DERIVED.items():
        out[p.name] = p
    for _, p in INDICATORS.items():
        out[p.name] = p
    return out


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_LOADED = threading.Event()
_LOAD_LOCK = threading.Lock()
_ERRORS: list[tuple[str, str]] = []


def _load_entry_points() -> None:
    try:
        eps = importlib.metadata.entry_points()
    except Exception as exc:  # pragma: no cover - environment dependent
        log.debug("entry point discovery failed: %s", exc)
        return
    for group in ENTRY_POINT_GROUPS.values():
        try:
            selected = eps.select(group=group)
        except AttributeError:  # pragma: no cover - very old importlib
            selected = eps.get(group, [])  # type: ignore[assignment]
        for ep in selected:
            try:
                obj = ep.load()
                if callable(obj) and getattr(obj, "__name__", "") == "register_all":
                    obj()
            except Exception as exc:
                _ERRORS.append((f"{group}:{ep.name}", repr(exc)))
                log.warning("failed loading plugin %s from %s: %s", ep.name, group, exc)


def _plugin_dirs() -> list[pathlib.Path]:
    dirs = [pathlib.Path.home() / ".quantlab" / "plugins"]
    env = os.environ.get("QUANTLAB_PLUGIN_PATH", "")
    dirs += [pathlib.Path(p).expanduser() for p in env.split(os.pathsep) if p.strip()]
    return [d for d in dirs if d.is_dir()]


def load_plugin_file(path: str | pathlib.Path) -> None:
    """Import a standalone .py plugin by path."""
    path = pathlib.Path(path).expanduser().resolve()
    mod_name = f"quantlab_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import plugin file {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)


def _load_plugin_dirs() -> None:
    for d in _plugin_dirs():
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                load_plugin_file(f)
            except Exception as exc:
                _ERRORS.append((str(f), repr(exc)))
                log.warning("failed loading plugin file %s: %s", f, exc)


def load_plugins(force: bool = False) -> None:
    """Idempotently populate every registry. Safe to call from anywhere."""
    if _LOADED.is_set() and not force:
        return
    with _LOAD_LOCK:
        if _LOADED.is_set() and not force:
            return
        # Builtins first so third parties can override them deliberately.
        for mod in (
            "quantlab.indicators",
            "quantlab.derived",
            "quantlab.providers",
            "quantlab.universe",
        ):
            try:
                m = importlib.import_module(mod)
                if hasattr(m, "register_all"):
                    m.register_all()
            except Exception as exc:  # pragma: no cover
                _ERRORS.append((mod, repr(exc)))
                log.warning("builtin %s failed to load: %s", mod, exc)
        _load_entry_points()
        _load_plugin_dirs()
        _LOADED.set()


def load_errors() -> list[tuple[str, str]]:
    return list(_ERRORS)


def describe() -> dict[str, dict[str, str]]:
    """Machine-readable inventory of everything registered."""
    load_plugins()
    out: dict[str, dict[str, str]] = {}
    for label, reg in (
        ("providers", PROVIDERS),
        ("universes", UNIVERSES),
        ("indicators", INDICATORS),
        ("derived", DERIVED),
    ):
        out[label] = {name: reg.origin(name) for name in reg.names()}
    return out
