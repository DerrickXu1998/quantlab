"""Identity: accounts, passwords, sessions, and who owns which row.

Kept as a library with no FastAPI in it (Constitution I), so the security
decisions -- uniform failures, constant-time verification, rate limiting,
revocable sessions -- are testable without a client and cannot be quietly undone
by a refactor of the API layer. ``quantlab.api.security`` is the thin adapter
that turns this into dependencies and status codes.
"""

from __future__ import annotations

from quantlab.auth.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    check_policy,
    hash_password,
    verify_password,
)
from quantlab.auth.service import (
    LOCAL_USER,
    AuthError,
    AuthService,
    RateLimited,
    auth_required,
)
from quantlab.auth.store import (
    SESSION_TTL,
    EmailAlreadyRegistered,
    Session,
    SqliteUserStore,
    User,
    normalise_email,
    select_user_store,
)

__all__ = [
    "LOCAL_USER",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "SESSION_TTL",
    "AuthError",
    "AuthService",
    "EmailAlreadyRegistered",
    "PasswordPolicyError",
    "RateLimited",
    "Session",
    "SqliteUserStore",
    "User",
    "auth_required",
    "check_policy",
    "hash_password",
    "normalise_email",
    "select_user_store",
    "verify_password",
]
