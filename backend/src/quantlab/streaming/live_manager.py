"""Client for the live gateway manager (live-ingest's ``manager`` service).

Each user's live prices come from their own IBKR login, run in a gateway of
their own; the manager starts, queues and stops those gateways. It is the
only service with Docker access, so the API never gets it: this module is a
plain HTTP client to the manager on the compose network, authenticated with
a shared token.

Passwords pass through ``connect`` and nowhere else -- not into a log, an
exception message or storage.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

URL_ENV = "QUANTLAB_LIVE_MANAGER_URL"
TOKEN_ENV = "QUANTLAB_LIVE_MANAGER_TOKEN"
TIMEOUT_SECONDS = 10


class ManagerUnavailable(RuntimeError):
    """The manager is not configured or did not answer."""


def configured() -> bool:
    return bool(os.environ.get(URL_ENV, "").strip() and os.environ.get(TOKEN_ENV, "").strip())


def _call(method: str, path: str, body: dict | None = None) -> dict:
    if not configured():
        raise ManagerUnavailable(
            f"live connections are not configured: {URL_ENV} or {TOKEN_ENV} is unset "
            "(it starts with the stack unless QUANTLAB_LIVE=off)"
        )
    url = os.environ[URL_ENV].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ[TOKEN_ENV]}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        # The manager's own words, never the request (which may hold a password).
        raise ManagerUnavailable(f"live gateway manager answered {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        kind = type(exc).__name__
        raise ManagerUnavailable(f"live gateway manager unreachable: {kind}") from None


def status(user_id: str) -> dict:
    return _call("GET", f"/sessions/{urllib.parse.quote(user_id, safe='')}")


def connect(user_id: str, username: str, password: str, trading_mode: str) -> dict:
    return _call(
        "POST",
        f"/sessions/{urllib.parse.quote(user_id, safe='')}",
        {"username": username, "password": password, "trading_mode": trading_mode},
    )


def disconnect(user_id: str) -> dict:
    return _call("DELETE", f"/sessions/{urllib.parse.quote(user_id, safe='')}")
