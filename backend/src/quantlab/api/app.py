"""FastAPI application shell.

Thin API layer (Constitution I): handlers only read from storage. The DB path
comes from the QUANTLAB_DB environment variable, falling back to
QUANTLAB_DB_PATH (set by the Docker image), default /data/quantlab.db;
``create_app`` accepts an explicit path for tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from quantlab import auth
from quantlab.api import routes
from quantlab.logging import get_logger
from quantlab.storage import backends, custom_rules, experiments, strategies

DEFAULT_DB_PATH = "/data/quantlab.db"

#: Comma-separated browser origins allowed to call this API.
CORS_ENV = "QUANTLAB_CORS_ORIGINS"

#: Explicit override for the interactive docs (``on``/``off``). Unset, the
#: docs follow the deployment posture -- see ``resolve_api_docs_enabled``.
API_DOCS_ENV = "QUANTLAB_API_DOCS"

logger = get_logger(__name__)


def resolve_db_path() -> str:
    return os.environ.get("QUANTLAB_DB") or os.environ.get("QUANTLAB_DB_PATH") or DEFAULT_DB_PATH


def resolve_cors_origins() -> list[str]:
    """Origins allowed to call the API from a browser.

    Empty by default. Served behind nginx or the Vite proxy the UI is
    same-origin and CORS never engages; only a split deployment -- the SPA on
    one domain, the API on another -- needs it.

    Deliberately an explicit allow-list with no wildcard fallback: defaulting
    to "*" would mean a deployment that forgot to configure this is open to
    every origin, and would look identical to one that was configured.
    """
    raw = os.environ.get(CORS_ENV, "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def resolve_api_docs_enabled() -> bool:
    """Whether to serve /docs and /openapi.json.

    The interactive docs publish the full API surface -- every route, every
    parameter -- to anyone who can reach the host, so the default follows the
    deployment posture: a deployment that requires auth is treated as
    production and keeps them off; the no-auth demo keeps them on.
    QUANTLAB_API_DOCS=on/off overrides either way.
    """
    raw = os.environ.get(API_DOCS_ENV, "").strip().lower()
    if raw:
        return raw in ("1", "true", "on", "yes")
    return not auth.auth_required()


def create_app(db_path: str | Path | None = None, backend=None) -> FastAPI:
    """Build the API app.

    The storage backend is chosen once at startup: the real warehouse when
    QUANTLAB_DB_URL and QUANTLAB_CH_URL are set, otherwise the synthetic
    SQLite dataset. Tests may inject one explicitly.
    """
    docs_enabled = resolve_api_docs_enabled()
    app = FastAPI(
        title="QuantLab Signal Viewer API",
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.db_path = str(db_path) if db_path is not None else resolve_db_path()
    app.state.backend = backend or backends.select_backend(app.state.db_path)
    # Mirrors select_backend: the warehouse when configured, else the demo.
    # Hand the store the warehouse itself (when the backend has one) so
    # experiment queries borrow its catalog pool rather than opening a second.
    wh = getattr(app.state.backend, "wh", None)
    app.state.experiments = experiments.select_experiment_store(app.state.db_path, wh=wh)
    # Identity and saved strategies. Both live with the demo database rather
    # than the bar store: they are small, mutable, and want foreign keys.
    app.state.auth = auth.AuthService(auth.select_user_store(app.state.db_path))
    app.state.strategies = strategies.select_strategy_store(app.state.db_path)
    # Template-based custom rules (feature 008): the same seam as experiments.
    app.state.custom_rules = custom_rules.select_custom_rule_store(app.state.db_path, wh=wh)
    app.include_router(routes.router, prefix="/api/v1")

    @app.middleware("http")
    async def unhandled_errors_as_json(request: Request, call_next):
        """Turn an unhandled exception into a 500 *inside* the CORS layer.

        Starlette answers an uncaught exception from ServerErrorMiddleware, which
        sits outside every user middleware -- CORS included. So a cross-origin
        500 went out with no Access-Control-Allow-Origin, the browser withheld
        it from the page, and the SPA could only report "Backend unreachable":
        a server bug disguised as a network fault. Registered before
        CORSMiddleware, so CORS wraps it and the error reaches the page as one.
        """
        try:
            return await call_next(request)
        except Exception:
            logger.exception(
                "unhandled_error",
                extra={"method": request.method, "path": request.url.path},
            )
            return JSONResponse(status_code=500, content={"detail": "internal server error"})

    origins = resolve_cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            # Credentials are carried in an Authorization header, never a
            # cookie, so the browser never attaches them to a cross-site
            # request on its own and there is no CSRF surface to defend.
            # allow_credentials stays off deliberately.
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["content-type", "authorization"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Headers that cost nothing and close whole classes of attack.

        No Content-Security-Policy: the SPA is served by nginx, not by this
        app, so a policy set here would apply only to the JSON API and to the
        docs page, and would give a false impression of coverage. That belongs
        in the frontend's nginx config, and is recorded as such in
        docs/SECURITY.md.
        """
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # An authenticated response must not be cached by a shared proxy and
        # then served to somebody else.
        if "authorization" in request.headers:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Forward exc.headers: without this the rebuilt response silently drops
        # headers the raise site set -- Retry-After on a 429, WWW-Authenticate
        # on a 401 -- and clients lose the information they need to back off.
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc.detail)},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return JSONResponse(status_code=422, content={"detail": detail})

    logger.info(
        "app_created",
        extra={
            "db_path": app.state.db_path,
            "backend": app.state.backend.name,
            "cors_origins": origins,
            "auth_required": auth.auth_required(),
        },
    )
    if not auth.auth_required():
        # Loud, because an operator who forgets this in production has an API
        # where every caller is the same user and nothing is private.
        logger.warning(
            "auth_disabled",
            extra={
                "detail": (
                    "QUANTLAB_AUTH_REQUIRED is false: every request is attributed "
                    "to the built-in local account and no data is private"
                )
            },
        )
    active_iterations = auth.passwords.iterations()
    if active_iterations < auth.passwords.DEFAULT_ITERATIONS:
        # Loud for the same reason: an operator who sets
        # QUANTLAB_PBKDF2_ITERATIONS below the default is trading real hashing
        # cost for speed, and a silent log line would not say so.
        logger.warning(
            "pbkdf2_iterations_below_default",
            extra={
                "detail": (
                    f"QUANTLAB_PBKDF2_ITERATIONS is {active_iterations}, below the "
                    f"default {auth.passwords.DEFAULT_ITERATIONS}: password hashing "
                    "is cheaper to attack than intended (fine for tests and local "
                    "development, wrong for production)"
                )
            },
        )
    return app


app = create_app()
