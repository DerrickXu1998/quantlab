"""The two things that break a container deploy before any request succeeds.

Both are invisible locally: behind nginx the frontend is same-origin so CORS
never engages, and docker-compose publishes a fixed port so nothing ever asks
the app to listen elsewhere. Both fail immediately on a platform that injects
$PORT and serves the UI from another domain.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from quantlab.api.app import create_app

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


# --- $PORT -----------------------------------------------------------------


def test_the_image_honours_an_injected_port():
    """Cloud Run, Fly and Render all inject $PORT and health-check it. A
    hardcoded --port means the revision never goes live."""
    text = DOCKERFILE.read_text()
    cmd = [line for line in text.splitlines() if line.startswith("CMD")]
    assert cmd, "Dockerfile has no CMD"

    assert "${PORT" in cmd[0], (
        "CMD must expand ${PORT} so the platform can choose the port; "
        f"found: {cmd[0]}"
    )
    # Shell form, or the variable is passed to uvicorn as a literal string.
    assert not re.match(r"^CMD\s*\[", cmd[0]), (
        "exec-form CMD does not expand variables; use shell form"
    )


def test_the_image_still_has_a_default_port():
    """Compose does not set $PORT, so the default keeps local dev working."""
    cmd = next(line for line in DOCKERFILE.read_text().splitlines() if line.startswith("CMD"))
    assert ":-8000}" in cmd, f"expected a :-8000 default, found: {cmd}"


# --- CORS ------------------------------------------------------------------


def _client(monkeypatch, origins: str | None):
    if origins is None:
        monkeypatch.delenv("QUANTLAB_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("QUANTLAB_CORS_ORIGINS", origins)
    return TestClient(create_app("/tmp/does-not-exist.db"))


def test_a_configured_origin_is_allowed(monkeypatch):
    client = _client(monkeypatch, "https://quantlab.vercel.app")

    response = client.get(
        "/api/v1/health", headers={"Origin": "https://quantlab.vercel.app"}
    )

    assert response.headers.get("access-control-allow-origin") == "https://quantlab.vercel.app"


def test_an_unlisted_origin_is_not_allowed(monkeypatch):
    """An allow-list that allows everything is not an allow-list."""
    client = _client(monkeypatch, "https://quantlab.vercel.app")

    response = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_several_origins_can_be_configured(monkeypatch):
    """Preview deployments mean more than one legitimate origin."""
    client = _client(
        monkeypatch, "https://quantlab.vercel.app, https://staging.quantlab.vercel.app"
    )

    for origin in ("https://quantlab.vercel.app", "https://staging.quantlab.vercel.app"):
        response = client.get("/api/v1/health", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin


def test_no_cors_headers_when_nothing_is_configured(monkeypatch):
    """Same-origin behind nginx needs no CORS, and a default of '*' would
    silently expose a deployment that forgot to configure it."""
    client = _client(monkeypatch, None)

    response = client.get("/api/v1/health", headers={"Origin": "https://anything.example"})

    assert "access-control-allow-origin" not in response.headers


def test_the_preflight_a_browser_actually_sends_succeeds(monkeypatch):
    """A cross-origin GET with no custom headers is simple and not preflighted,
    but POST /runs sends application/json and is. That is the request the
    workbench depends on."""
    client = _client(monkeypatch, "https://quantlab.vercel.app")

    response = client.options(
        "/api/v1/runs",
        headers={
            "Origin": "https://quantlab.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://quantlab.vercel.app"
    assert "POST" in response.headers.get("access-control-allow-methods", "")
