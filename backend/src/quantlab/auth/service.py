"""Registration, login, logout: the library half, with no HTTP in it.

The security-relevant decisions all live here rather than in the route handlers,
so they can be tested without a client and cannot be quietly undone by a
refactor of the API layer (Constitution I).

Two of them are worth naming:

**Login is not an account-enumeration oracle.** An unknown email and a wrong
password produce the same error, and the unknown-email path still performs a
full PBKDF2 verification against a dummy hash so the two take the same time.
Skipping the hash for an unknown address makes "does this person have an
account?" answerable with a stopwatch.

**Failed logins are rate limited per email.** The limit is keyed on the address
being attacked rather than on the source address, because the thing being
protected is one account against many clients. It is process-local, which is a
real limitation on a multi-worker deployment and is recorded in
``docs/SECURITY.md``.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections import defaultdict, deque

from quantlab.auth import passwords
from quantlab.auth.store import (
    EmailAlreadyRegistered,
    Session,
    SqliteUserStore,
    User,
    normalise_email,
)
from quantlab.logging import get_logger

logger = get_logger(__name__)

#: Whether the API demands a token at all. Unset or true means yes. The demo
#: and the existing smoke tests run with it false, which binds every request to
#: a single built-in account so ownership columns are still populated and the
#: two modes do not diverge in shape.
AUTH_REQUIRED_ENV = "QUANTLAB_AUTH_REQUIRED"

#: The account requests are attributed to when auth is switched off. A real id,
#: so rows written in demo mode are indistinguishable in shape from real ones.
LOCAL_USER = User(
    id="local",
    email="local@quantlab.invalid",
    created_at="1970-01-01T00:00:00+00:00",
)

MAX_FAILED_ATTEMPTS = 8
LOCKOUT_WINDOW_SECONDS = 15 * 60

#: A hash of a password nobody has, verified against when the email is unknown
#: so that path costs what a real one does.
#:
#: Built lazily at the *current* iteration count rather than hardcoded. A
#: hardcoded constant would be pinned to whatever cost it was generated at, and
#: the unknown-email path would then be measurably faster than the real one --
#: which is exactly the oracle the dummy verification exists to close.
_dummy: tuple[int, str] | None = None
_dummy_lock = threading.Lock()


def _dummy_hash() -> str:
    global _dummy
    rounds = passwords.iterations()
    with _dummy_lock:
        if _dummy is None or _dummy[0] != rounds:
            _dummy = (rounds, passwords.hash_password(secrets.token_urlsafe(32), rounds=rounds))
        return _dummy[1]


class AuthError(Exception):
    """Credentials were not accepted. Deliberately says no more than that."""


class RateLimited(Exception):
    """Too many failed attempts against this address."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"too many failed sign-in attempts; try again in {retry_after}s")
        self.retry_after = retry_after


def auth_required() -> bool:
    raw = os.environ.get(AUTH_REQUIRED_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


class _FailureTracker:
    """Recent failed attempts per email, in memory."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, address: str, now: float) -> deque[float]:
        attempts = self._attempts[address]
        while attempts and now - attempts[0] > LOCKOUT_WINDOW_SECONDS:
            attempts.popleft()
        return attempts

    def check(self, address: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = self._prune(address, now)
            if len(attempts) >= MAX_FAILED_ATTEMPTS:
                retry_after = int(LOCKOUT_WINDOW_SECONDS - (now - attempts[0])) + 1
                raise RateLimited(retry_after)

    def record_failure(self, address: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(address, now).append(now)

    def clear(self, address: str) -> None:
        with self._lock:
            self._attempts.pop(address, None)

    def reset(self) -> None:
        """Test seam. Never called by the application."""
        with self._lock:
            self._attempts.clear()


class AuthService:
    """Everything the API layer is allowed to ask of identity."""

    def __init__(self, store: SqliteUserStore) -> None:
        self.store = store
        self._failures = _FailureTracker()

    # -- registration ------------------------------------------------------

    def register(self, email: str, password: str) -> Session:
        address = normalise_email(email)
        if not address or "@" not in address:
            raise passwords.PasswordPolicyError("a valid email address is required")
        # Raises PasswordPolicyError, which the API turns into a 422 naming the
        # actual problem -- unlike login, registration *should* be helpful.
        passwords.check_policy(password)
        user = self.store.create_user(address, passwords.hash_password(password))
        logger.info("user_registered", extra={"user_id": user.id})
        return self.store.create_session(user)

    # -- login -------------------------------------------------------------

    def login(self, email: str, password: str) -> Session:
        address = normalise_email(email)
        self._failures.check(address)

        found = self.store.find_by_email(address)
        if found is None:
            # Verify anyway: an unknown address must cost what a known one does.
            passwords.verify_password(password or "", _dummy_hash())
            self._failures.record_failure(address)
            raise AuthError("invalid email or password")

        user, stored_hash = found
        if not passwords.verify_password(password or "", stored_hash):
            self._failures.record_failure(address)
            logger.info("login_failed", extra={"user_id": user.id})
            raise AuthError("invalid email or password")

        # A disabled account is refused with the same message, after the same
        # work, so disabling somebody does not announce itself.
        if user.disabled:
            self._failures.record_failure(address)
            raise AuthError("invalid email or password")

        self._failures.clear(address)

        # Transparent cost upgrade: an old hash is re-derived at the current
        # iteration count now that the plaintext is briefly in hand.
        if passwords.needs_rehash(stored_hash):
            self.store.set_password_hash(user.id, passwords.hash_password(password))
            logger.info("password_rehashed", extra={"user_id": user.id})

        logger.info("login_succeeded", extra={"user_id": user.id})
        return self.store.create_session(user)

    # -- sessions ----------------------------------------------------------

    def resolve(self, token: str | None) -> User | None:
        if not auth_required():
            return LOCAL_USER
        if not token:
            return None
        return self.store.resolve_session(token)

    def logout(self, token: str) -> bool:
        return self.store.delete_session(token)


__all__ = [
    "LOCAL_USER",
    "AuthError",
    "AuthService",
    "EmailAlreadyRegistered",
    "RateLimited",
    "Session",
    "User",
    "auth_required",
]
