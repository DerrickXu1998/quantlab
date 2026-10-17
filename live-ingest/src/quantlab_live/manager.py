"""Per-user IBKR sessions: one gateway and one collector per connected user.

Live prices come from each user's own IBKR login -- one account's market
data is licensed to that account's holder -- so every user who connects gets
a gateway logged in as them, and a collector streaming their own leases.

Lifecycle of a session::

    queued ──▶ starting ──▶ logging_in ──▶ connected
       │           │             │              │
       └───────────┴──── failed ◀┘   (idle, disconnect) ──▶ gone

- **Capacity.** At most ``max_gateways`` run at once (each is a ~1 GB JVM);
  the rest wait in a FIFO queue. A queued password is held in this process's
  memory only, and dropped once handed to a gateway or once the user stops
  asking (``QUEUE_IDLE_SECONDS``).
- **Login.** Progress is read from the gateway's own output and from whether
  its API port answers. A failed login is final: the container is removed
  and nothing retries it, because IBKR locks accounts after repeated failures.
- **Idle.** A gateway nobody has used for ``IDLE_SECONDS`` (no leases, no
  status polls) is stopped, freeing its slot.
- **Restarts.** On start the manager re-adopts labelled gateways still running,
  so redeploying it does not log everybody out.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

TICK_SECONDS = 2.0
LOGIN_TIMEOUT_SECONDS = 5 * 60
IDLE_SECONDS = 15 * 60
QUEUE_IDLE_SECONDS = 2 * 60
#: How often a logging-in gateway's output is read for progress.
LOG_POLL_SECONDS = 4.0

#: Lowercased phrases in IB Gateway / IBC output. Matched loosely: the exact
#: wording varies across gateway versions.
FAILED_LOGIN = (
    "unrecognized username or password",
    "invalid username or password",
    "login failed",
    "incorrect password",
    "account is locked",
)
TWOFA = ("second factor", "two factor", "ib key", "2fa")

LOGGING_IN = "Logging in to IBKR. If an IB Key notification appears on your phone, approve it."
APPROVE_2FA = "Approve the IB Key notification on your phone to finish logging in."


@dataclass
class Session:
    owner: str
    ib_username: str
    trading_mode: str
    state: str
    requested_at: float
    last_seen: float
    detail: str = ""
    password: str | None = field(default=None, repr=False)
    gateway: str | None = None
    collector: Any = None
    task: asyncio.Task | None = None
    stop: asyncio.Event | None = None
    started_at: float = 0.0
    last_log_check: float = 0.0


class Manager:
    def __init__(
        self,
        gateways: Any,
        make_collector: Callable[[str, str], Any],
        max_gateways: int = 2,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """``make_collector(owner, gateway_host)`` builds a user's collector."""
        self.gateways = gateways
        self.make_collector = make_collector
        self.max_gateways = max_gateways
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self.queue: list[str] = []
        self._lock = asyncio.Lock()

    # --- the API the backend calls -----------------------------------------

    def view(self, owner: str) -> dict:
        session = self.sessions.get(owner)
        if session is None:
            return {"state": "none"}
        session.last_seen = self.clock()
        out = {
            "state": session.state,
            "detail": session.detail,
            "queue_position": None,
            "ib_username": session.ib_username,
            "trading_mode": session.trading_mode,
        }
        if session.state == "queued":
            out["queue_position"] = self.queue.index(owner) + 1
        return out

    async def connect(self, owner: str, username: str, password: str, trading_mode: str) -> dict:
        async with self._lock:
            current = self.sessions.get(owner)
            if (
                current is not None
                and current.state in ("starting", "logging_in", "connected", "queued")
                and current.ib_username == username
                and current.trading_mode == trading_mode
            ):
                return self.view(owner)  # already on its way; no second login
            if current is not None:
                await self._end(owner)
            now = self.clock()
            self.sessions[owner] = Session(
                owner=owner,
                ib_username=username,
                trading_mode=trading_mode,
                state="queued",
                requested_at=now,
                last_seen=now,
                password=password,
                detail="Waiting for a free live-data slot.",
            )
            self.queue.append(owner)
            await self._promote()
            return self.view(owner)

    async def disconnect(self, owner: str) -> dict:
        async with self._lock:
            await self._end(owner)
            await self._promote()
        return {"state": "none"}

    # --- the loop -------------------------------------------------------------

    async def adopt(self) -> None:
        """Take back gateways a previous manager left running."""
        for info in await asyncio.to_thread(self.gateways.running):
            if not info.owner or info.owner in self.sessions:
                continue
            if info.status != "running":
                await asyncio.to_thread(self.gateways.remove, info.name)
                continue
            now = self.clock()
            session = Session(
                owner=info.owner,
                ib_username=info.ib_username,
                trading_mode=info.trading_mode,
                state="logging_in",
                requested_at=now,
                last_seen=now,
                detail=LOGGING_IN,
                gateway=info.name,
                started_at=now,
            )
            self.sessions[info.owner] = session
            self._start_collector(session)
            log.info("re-adopted the gateway of one user")

    async def tick(self) -> None:
        async with self._lock:
            now = self.clock()
            for owner in list(self.sessions):
                session = self.sessions[owner]
                if session.state == "queued":
                    if now - session.last_seen > QUEUE_IDLE_SECONDS:
                        await self._end(owner)  # nobody waiting any more
                    continue
                if session.state in ("starting", "logging_in", "connected"):
                    await self._check(session, now)
            await self._promote()

    async def run(self, stop: asyncio.Event) -> None:
        await self.adopt()
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("manager tick failed; carrying on")
            try:
                await asyncio.wait_for(stop.wait(), TICK_SECONDS)
            except TimeoutError:
                pass

    # --- internals ----------------------------------------------------------

    def _active(self) -> int:
        return sum(
            1 for s in self.sessions.values() if s.state in ("starting", "logging_in", "connected")
        )

    async def _promote(self) -> None:
        while self.queue and self._active() < self.max_gateways:
            owner = self.queue.pop(0)
            session = self.sessions.get(owner)
            if session is None or session.state != "queued":
                continue
            password, session.password = session.password, None
            session.state, session.detail = "starting", "Starting your IBKR gateway."
            session.started_at = self.clock()
            try:
                session.gateway = await asyncio.to_thread(
                    self.gateways.start,
                    owner,
                    session.ib_username,
                    password,
                    session.trading_mode,
                )
            except Exception as exc:
                log.exception("starting a gateway failed")
                session.state = "failed"
                session.detail = f"Could not start a gateway: {type(exc).__name__}."
                continue
            finally:
                del password
            session.state, session.detail = "logging_in", LOGGING_IN
            self._start_collector(session)

    def _start_collector(self, session: Session) -> None:
        session.stop = asyncio.Event()
        session.collector = self.make_collector(session.owner, session.gateway)
        session.task = asyncio.create_task(session.collector.run(session.stop))

    async def _check(self, session: Session, now: float) -> None:
        connected = session.collector is not None and session.collector.gateway.connected()
        if connected:
            if session.state != "connected":
                log.info("a user's gateway is connected")
            session.state, session.detail = "connected", ""
            last_used = max(session.last_seen, session.collector.last_lease_at)
            if now - last_used > IDLE_SECONDS:
                log.info("stopping an idle gateway")
                await self._end(session.owner)
            return

        info = await asyncio.to_thread(self.gateways.info, session.gateway)
        if info is None or info.status not in ("created", "running", "restarting"):
            await self._fail(session, self._exit_reason(session))
            return
        if now - session.last_log_check >= LOG_POLL_SECONDS:
            session.last_log_check = now
            output = (await asyncio.to_thread(self.gateways.logs, session.gateway)).lower()
            if any(phrase in output for phrase in FAILED_LOGIN):
                await self._fail(session, "IBKR rejected the username or password.")
                return
            if any(phrase in output for phrase in TWOFA):
                session.detail = APPROVE_2FA
        if session.state == "connected":
            # Was connected, lost it: IBC's daily restart, or IBKR's weekly
            # re-authentication, which needs the user again.
            session.state, session.detail = "logging_in", "Reconnecting to IBKR."
            session.started_at = now
        if now - session.started_at > LOGIN_TIMEOUT_SECONDS:
            await self._fail(session, "Login did not complete within 5 minutes.")

    def _exit_reason(self, session: Session) -> str:
        if session.detail == APPROVE_2FA:
            return "The IB Key notification was not approved in time."
        return "The gateway stopped before logging in."

    async def _fail(self, session: Session, reason: str) -> None:
        log.warning("a user's gateway failed: %s", reason)
        await self._stop_gateway(session)
        session.state, session.detail = "failed", f"{reason} Connect again to retry."

    async def _end(self, owner: str) -> None:
        session = self.sessions.pop(owner, None)
        if owner in self.queue:
            self.queue.remove(owner)
        if session is not None:
            session.password = None
            await self._stop_gateway(session)

    async def _stop_gateway(self, session: Session) -> None:
        if session.stop is not None:
            session.stop.set()
        if session.task is not None:
            session.task.cancel()
            session.task = None
        if session.gateway is not None:
            try:
                await asyncio.to_thread(self.gateways.remove, session.gateway)
            except Exception:
                log.exception("removing a gateway failed")
            session.gateway = None
