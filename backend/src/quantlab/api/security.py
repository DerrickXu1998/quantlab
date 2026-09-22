"""The thin adapter between :mod:`quantlab.auth` and FastAPI.

Everything security-relevant is decided in the library. This module only turns
a request into a user and a failure into a status code (Constitution I), so the
rules cannot be quietly changed by editing a route.

One convention is load-bearing throughout the API: **a row that is not yours
reads as absent.** Another user's run is a 404, never a 403, because a 403
confirms the row exists -- which is information the caller has not earned. The
only place that distinction is visible is here, in the helper every handler
uses to resolve a run.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from quantlab.auth import LOCAL_USER, AuthService, User, auth_required


def service(request: Request) -> AuthService:
    return request.app.state.auth


def bearer_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    """The token from an ``Authorization: Bearer <token>`` header.

    A malformed header is treated as no token at all rather than as an error:
    the caller is unauthenticated either way, and distinguishing the two only
    tells a prober which of their guesses was closer.
    """
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def current_user(
    request: Request,
    token: Annotated[str | None, Depends(bearer_token)],
) -> User:
    """The authenticated user, or 401.

    With ``QUANTLAB_AUTH_REQUIRED=false`` this is always the built-in local
    account, so ownership columns are still populated and the two modes do not
    diverge in shape -- the demo writes the same rows a real deployment does.
    """
    user = service(request).resolve(token)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def owner_scope(user: User) -> str | None:
    """The owner id to filter storage reads by.

    ``None`` in single-user mode, which means "do not filter" -- and is what
    keeps runs recorded before accounts existed reachable. Once auth is on,
    every query is scoped, including to the local user's own id if somebody
    turns auth on over an existing database.
    """
    if not auth_required():
        return None
    return user.id


def is_local(user: User) -> bool:
    return user.id == LOCAL_USER.id
