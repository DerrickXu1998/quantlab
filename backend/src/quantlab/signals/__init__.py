"""Signal rules: the plugin registry, the engine, and the shipped catalogue.

Importing this package registers every builtin rule. That is deliberate: the
registry is the single source of truth for what the API can offer, and having
each caller remember its own ``import builtins  # noqa: F401`` is how a rule
ends up visible in one code path and missing from another. Anything that
imports a submodule of ``quantlab.signals`` runs this first, so the catalogue is
always complete.

A third-party rule still registers the same way -- decorate and import -- so
nothing here is privileged beyond shipping in the box.
"""

from __future__ import annotations

from quantlab.signals import builtins as _builtins  # noqa: F401
from quantlab.signals import fundamental as _fundamental  # noqa: F401
from quantlab.signals import library as _library  # noqa: F401
