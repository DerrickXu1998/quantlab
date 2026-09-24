"""Password hashing and the password policy.

**PBKDF2-HMAC-SHA256, not argon2 or bcrypt.** Argon2id is the better primitive
and if this were a consumer product it would be the right call. It is not used
here because the constitution requires new third-party dependencies to be
justified against the adapter and plugin contracts, and the backend image
deliberately carries no native build toolchain -- ``argon2-cffi`` and ``bcrypt``
both ship compiled extensions. PBKDF2 is in the standard library, is FIPS-blessed,
and at 600k iterations is a genuine obstacle to offline cracking. It is weaker
than argon2 against GPU and ASIC attackers specifically because it needs almost
no memory, and that trade-off is recorded in ``docs/SECURITY.md`` rather than
being quietly made here.

Every parameter below is pinned in the stored hash string, so raising the
iteration count later does not invalidate existing passwords: an old hash
verifies against its own recorded cost and is transparently upgraded on the
next successful login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import unicodedata

ALGORITHM = "pbkdf2_sha256"

#: OWASP's 2023 floor for PBKDF2-HMAC-SHA256. Roughly a third of a second per
#: hash on a modern core, which is tolerable for a login and expensive at scale
#: for anyone working through a stolen database.
DEFAULT_ITERATIONS = 600_000

#: Tests and local development need logins that are not a third of a second
#: each. Lowering this in production is a real weakening, so it is read once,
#: floored, and the floor is not negotiable.
ITERATIONS_ENV = "QUANTLAB_PBKDF2_ITERATIONS"
MINIMUM_ITERATIONS = 1_000

SALT_BYTES = 16

#: Long enough to matter, short enough that nobody pastes a novel. The upper
#: bound is a denial-of-service guard, not a security one: PBKDF2 over a 10MB
#: "password" is a free CPU burn for an attacker.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

#: A deliberately tiny list. A real deployment should check against a proper
#: breach corpus; refusing the handful of passwords that people genuinely do
#: pick first is still worth more than refusing none.
_OBVIOUS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "passw0rd123",
        "123456789012",
        "1234567890123",
        "qwertyuiop12",
        "administrator",
        "letmein12345",
        "iloveyou1234",
        "quantlab1234",
        "changeme1234",
    }
)


class PasswordPolicyError(ValueError):
    """The password is unacceptable, with a reason a user can act on."""


def iterations() -> int:
    raw = os.environ.get(ITERATIONS_ENV)
    if not raw:
        return DEFAULT_ITERATIONS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_ITERATIONS
    return max(value, MINIMUM_ITERATIONS)


def normalise(password: str) -> bytes:
    """NFKC, then UTF-8.

    Without normalisation a password typed with a composed accent and one typed
    with a combining accent are different byte strings, and a user who switches
    keyboard or platform is locked out of their own account for a reason no
    error message could ever explain.
    """
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def check_policy(password: str) -> None:
    """Raise :class:`PasswordPolicyError` if ``password`` is unacceptable."""
    if not isinstance(password, str):
        raise PasswordPolicyError("password must be text")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(normalise(password)) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"password must be at most {MAX_PASSWORD_LENGTH} bytes"
        )
    stripped = password.strip()
    if not stripped:
        raise PasswordPolicyError("password must not be only whitespace")
    if password.lower() in _OBVIOUS:
        raise PasswordPolicyError("password is too common; choose another")
    if len(set(password)) < 4:
        raise PasswordPolicyError(
            "password repeats too few distinct characters; choose another"
        )


def hash_password(password: str, *, rounds: int | None = None) -> str:
    """``pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>``.

    The cost and salt travel with the hash, which is what makes the iteration
    count upgradable without a mass password reset.
    """
    check_policy(password)
    rounds = rounds or iterations()
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", normalise(password), salt, rounds)
    return f"{ALGORITHM}${rounds}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification. False for anything malformed.

    Never raises on a bad stored hash: a corrupt row must read as "wrong
    password", not as a 500 that tells an attacker the row exists.
    """
    if len(normalise(password)) > MAX_PASSWORD_LENGTH:
        # Registration refuses these; hashing one anyway is a free CPU burn
        # for whoever sent it. Internal callers have no schema in front of
        # them, so the guard lives here too.
        return False
    try:
        algorithm, raw_rounds, salt_b64, digest_b64 = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        rounds = int(raw_rounds)
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
    except (ValueError, AttributeError):
        return False
    if rounds < 1:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", normalise(password), salt, rounds)
    return hmac.compare_digest(candidate, expected)


def needs_rehash(encoded: str) -> bool:
    """True when a stored hash is cheaper than the current cost setting."""
    try:
        algorithm, raw_rounds, _, _ = encoded.split("$")
    except ValueError:
        return True
    return algorithm != ALGORITHM or int(raw_rounds) < iterations()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))
