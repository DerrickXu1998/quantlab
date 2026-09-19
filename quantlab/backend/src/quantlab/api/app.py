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
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from quantlab.api import routes
from quantlab.logging import get_logger

DEFAULT_DB_PATH = "/data/quantlab.db"

logger = get_logger(__name__)


def resolve_db_path() -> str:
    return os.environ.get("QUANTLAB_DB") or os.environ.get("QUANTLAB_DB_PATH") or DEFAULT_DB_PATH


def create_app(db_path: str | Path | None = None) -> FastAPI:
    """Build the API app bound to a DB path (defaults to env var / /data)."""
    app = FastAPI(title="QuantLab Signal Viewer API", version="0.1.0")
    app.state.db_path = str(db_path) if db_path is not None else resolve_db_path()
    app.include_router(routes.router, prefix="/api/v1")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return JSONResponse(status_code=422, content={"detail": detail})

    logger.info("app_created", extra={"db_path": app.state.db_path})
    return app


app = create_app()
