"""The manager's internal HTTP API, for the quantlab backend only.

Listens on the compose network (never published) and demands the shared
token on every call. A connect request carries a user's IBKR password: it is
read, handed to the manager and never logged -- aiohttp's access log records
the method and path only, and no handler logs a body.
"""

from __future__ import annotations

import hmac

from aiohttp import web

from quantlab_live.manager import Manager

MODES = ("paper", "live")


def make_app(manager: Manager, token: str) -> web.Application:
    @web.middleware
    async def authenticate(request: web.Request, handler):
        if request.path == "/healthz":
            return await handler(request)
        supplied = request.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(supplied, f"Bearer {token}"):
            return web.json_response({"detail": "unauthorized"}, status=401)
        return await handler(request)

    async def healthz(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def status(request: web.Request) -> web.Response:
        return web.json_response(manager.view(request.match_info["owner"]))

    async def connect(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"detail": "body must be JSON"}, status=400)
        username = body.get("username") if isinstance(body, dict) else None
        password = body.get("password") if isinstance(body, dict) else None
        mode = body.get("trading_mode", "paper") if isinstance(body, dict) else None
        if (
            not isinstance(username, str)
            or not username
            or not isinstance(password, str)
            or not password
        ):
            return web.json_response({"detail": "username and password are required"}, status=400)
        if mode not in MODES:
            return web.json_response({"detail": "trading_mode must be paper or live"}, status=400)
        view = await manager.connect(request.match_info["owner"], username, password, mode)
        return web.json_response(view, status=202)

    async def disconnect(request: web.Request) -> web.Response:
        return web.json_response(await manager.disconnect(request.match_info["owner"]))

    app = web.Application(middlewares=[authenticate], client_max_size=16 * 1024)
    app.add_routes(
        [
            web.get("/healthz", healthz),
            web.get("/sessions/{owner}", status),
            web.post("/sessions/{owner}", connect),
            web.delete("/sessions/{owner}", disconnect),
        ]
    )
    return app
