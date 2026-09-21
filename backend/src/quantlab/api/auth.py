"""Authentication: password hashing, session tokens, and the route guard.

Stdlib only (Constitution: the backend carries no heavy dependencies):
passwords are hashed with ``hashlib.pbkdf2_hmac`` (SHA-256, 600k iterations,
per-user salt) and compared with ``hmac.compare_digest``; sessions are
``secrets.token_urlsafe`` bearer tokens stored SHA-256-hashed with a 14-day
rolling expiry.

The whole feature is switched by ``QUANTLAB_AUTH`` (default ``on``). With
``off`` the ``require_session`` dependency is a no-op and the auth routes
answer 404, so pre-auth deployments and the test suite behave exactly as
before.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from quantlab.api import schemas
from quantlab.storage import auth as auth_store

#: PBKDF2 work factor (OWASP's 2024 floor for SHA-256). ``PBKDF2_ITERATIONS``
#: is read at call time so tests can trade strength for speed.
DEFAULT_PBKDF2_ITERATIONS = 600_000
PBKDF2_ITERATIONS = DEFAULT_PBKDF2_ITERATIONS

#: Browser cookie carrying the session token. HttpOnly + SameSite=Lax; Secure
#: only when QUANTLAB_AUTH_COOKIE_SECURE is set (local dev is plain http).
SESSION_COOKIE = "quantlab_session"

AUTH_ENV = "QUANTLAB_AUTH"
AUTH_COOKIE_SECURE_ENV = "QUANTLAB_AUTH_COOKIE_SECURE"

router = APIRouter()


def resolve_auth_enabled() -> bool:
    """QUANTLAB_AUTH: on unless explicitly turned off."""
    return os.environ.get(AUTH_ENV, "on").strip().lower() not in ("off", "0", "false")


def resolve_auth_cookie_secure() -> bool:
    """Secure cookie flag: opt-in, for deployments behind TLS."""
    return os.environ.get(AUTH_COOKIE_SECURE_ENV, "").strip().lower() in ("on", "1", "true")


# --- Passwords ---------------------------------------------------------------


def hash_password(password: str) -> str:
    """``pbkdf2_sha256$<iterations>$<salt b64>$<digest b64>`` — self-describing,
    so a future iteration bump needs no migration."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against a stored ``hash_password`` record."""
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(digest, expected)


# --- Session tokens ------------------------------------------------------------


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Only this digest is ever stored or looked up."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- Login rate limiting ---------------------------------------------------------


class LoginRateLimiter:
    """In-memory per-IP cap on failed logins: `max_attempts` failures inside
    `window_seconds` blocks further attempts until the window slides past.

    Deliberately process-local and failure-only: this is a single-node
    research tool, and the goal is to blunt online guessing, not to build
    distributed abuse infrastructure.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: float = 60.0) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        now = time.monotonic()
        attempts = self._failures.setdefault(key, deque())
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()
        return attempts

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)


# --- The route guard ------------------------------------------------------------


def require_session(request: Request) -> dict | None:
    """FastAPI dependency guarding every authenticated route.

    Returns the authenticated user ``{id, username, is_admin}``, or None when
    auth is disabled — which is also how callers tell "no scoping" apart from
    a real user. Raises 401 when auth is on and the session cookie is absent,
    unknown, or expired.
    """
    if not request.app.state.auth_enabled:
        return None
    token = request.cookies.get(SESSION_COOKIE)
    user = (
        request.app.state.auth.get_session_user(hash_token(token), auth_store.utcnow())
        if token
        else None
    )
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def user_id_of(user: dict | None) -> int | None:
    """The scoping key for ExperimentStore calls: None means unscoped."""
    return user["id"] if user else None


# --- Auth endpoints -------------------------------------------------------------


def _auth_enabled_or_404(request: Request) -> None:
    """With QUANTLAB_AUTH=off the auth surface does not exist."""
    if not request.app.state.auth_enabled:
        raise HTTPException(
            status_code=404, detail="authentication is disabled (QUANTLAB_AUTH=off)"
        )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _public_user(user: dict) -> dict:
    """Never let password_hash near a response."""
    return {"id": user["id"], "username": user["username"], "is_admin": user["is_admin"]}


@router.post(
    "/auth/register",
    response_model=schemas.User,
    status_code=201,
    tags=["auth"],
    operation_id="registerUser",
)
def register(request: Request, body: schemas.AuthCredentials) -> dict:
    """Public only while zero users exist — and that first user becomes the
    admin. Afterwards an admin session is required."""
    _auth_enabled_or_404(request)
    store = request.app.state.auth
    bootstrap = store.count_users() == 0
    if not bootstrap:
        user = require_session(request)
        if not user["is_admin"]:
            raise HTTPException(status_code=403, detail="only an admin can register new users")
    if store.get_user_by_username(body.username) is not None:
        raise HTTPException(status_code=409, detail=f"username taken: {body.username}")
    created = store.create_user(body.username, hash_password(body.password), is_admin=bootstrap)
    return _public_user(created)


@router.post(
    "/auth/login",
    response_model=schemas.User,
    tags=["auth"],
    operation_id="login",
)
def login(request: Request, response: Response, body: schemas.AuthCredentials) -> dict:
    _auth_enabled_or_404(request)
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = _client_ip(request)
    if limiter.blocked(ip):
        raise HTTPException(status_code=429, detail="too many attempts; try again later")
    store = request.app.state.auth
    user = store.get_user_by_username(body.username)
    if user is None or not verify_password(body.password, user["password_hash"]):
        limiter.record_failure(ip)
        raise HTTPException(status_code=401, detail="invalid username or password")
    limiter.clear(ip)

    token = new_session_token()
    store.create_session(user["id"], hash_token(token), auth_store.utcnow())
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(auth_store.SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.app.state.auth_cookie_secure,
    )
    return _public_user(user)


@router.post(
    "/auth/logout",
    status_code=204,
    tags=["auth"],
    operation_id="logout",
)
def logout(
    request: Request,
    response: Response,
    user: Annotated[dict | None, Depends(require_session)],
) -> None:
    _auth_enabled_or_404(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        request.app.state.auth.delete_session(hash_token(token))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get(
    "/auth/me",
    response_model=schemas.UserPublic,
    tags=["auth"],
    operation_id="getCurrentUser",
)
def get_current_user(
    request: Request, user: Annotated[dict | None, Depends(require_session)]
) -> dict:
    _auth_enabled_or_404(request)
    return {"id": user["id"], "username": user["username"]}
