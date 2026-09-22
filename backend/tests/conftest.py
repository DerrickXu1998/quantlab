"""Suite-wide defaults.

**Authentication is off by default here.** Every test written before accounts
existed calls the API without a token, and the contract's promise is precisely
that ``QUANTLAB_AUTH_REQUIRED=false`` leaves the API reachable exactly as it was
-- so those tests continuing to pass unmodified is the evidence for that
promise, not a way of dodging it. The suites that exercise authentication and
per-user isolation turn it back on explicitly with ``monkeypatch.setenv``.

**PBKDF2 runs at its floor.** 600k iterations is a third of a second per hash,
which would add minutes to a suite that registers accounts freely. The floor in
``quantlab.auth.passwords`` is what stops this knob from silently weakening a
deployment; it cannot be lowered past 1,000 anywhere.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QUANTLAB_PBKDF2_ITERATIONS", "1000")
# Set at import, not only by the fixture below: a module- or session-scoped
# fixture is built before any function-scoped one, so a suite that creates its
# client and its runs in a module fixture would otherwise see the default
# (enforced) mode and answer 401 before the fixture could take effect.
os.environ.setdefault("QUANTLAB_AUTH_REQUIRED", "false")


@pytest.fixture(autouse=True)
def _single_user_by_default(monkeypatch, request):
    """Bind requests to the built-in local account unless a test says otherwise.

    Opt out by setting the variable inside the test: ``monkeypatch`` restores
    the environment afterwards either way, so the two modes cannot leak into
    each other through ordering.
    """
    if request.node.get_closest_marker("auth_required"):
        monkeypatch.setenv("QUANTLAB_AUTH_REQUIRED", "true")
    else:
        monkeypatch.setenv("QUANTLAB_AUTH_REQUIRED", "false")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "auth_required: run this test with authentication enforced"
    )
