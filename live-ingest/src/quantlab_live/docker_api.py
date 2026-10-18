"""Per-user IB Gateway containers, through the Docker Engine API.

The only Docker-touching code in quantlab, and it runs only in the gateway
manager -- the API never gets the socket. Each gateway is labelled with its
owner so a restarted manager can find and re-adopt the ones still running.

A user's IBKR password is passed as the container's environment: it lives in
that container, for that container's life, and is removed with it. It is
never written to quantlab's databases or logs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

LABEL = "quantlab.live"
OWNER_LABEL = "quantlab.live.owner"
USERNAME_LABEL = "quantlab.live.ib_username"
MODE_LABEL = "quantlab.live.mode"


@dataclass(frozen=True)
class GatewayInfo:
    name: str
    owner: str
    ib_username: str
    trading_mode: str
    status: str  # created | running | exited | ...


def gateway_name(owner: str) -> str:
    """A stable, non-identifying container name per user."""
    return "quantlab-ibgw-" + hashlib.sha256(owner.encode()).hexdigest()[:12]


class DockerGateways:
    def __init__(self, image: str, network: str, memory: str = "1g") -> None:
        import docker

        self._client = docker.from_env()
        self._image = image
        self._network = network
        self._memory = memory

    def start(self, owner: str, ib_username: str, password: str, trading_mode: str) -> str:
        name = gateway_name(owner)
        self.remove(name)
        self._client.containers.run(
            self._image,
            name=name,
            detach=True,
            network=self._network,
            mem_limit=self._memory,
            # Never restarted by Docker: a login that failed must not be
            # retried behind the user's back -- IBKR locks accounts that way.
            # The manager restarts gateways that stopped after connecting
            # (DockerGateways.restart); IBC restarts the gateway process inside
            # the container daily.
            restart_policy={"Name": "no"},
            labels={
                LABEL: "gateway",
                OWNER_LABEL: owner,
                USERNAME_LABEL: ib_username,
                MODE_LABEL: trading_mode,
            },
            environment={
                "TWS_USERID": ib_username,
                "TWS_PASSWORD": password,
                "TRADING_MODE": trading_mode,
                # Nothing in quantlab can place an order through this login.
                "READ_ONLY_API": "yes",
                # Always on: an unapproved IB Key prompt (IBKR's weekly forced
                # re-login, for live accounts) is asked again rather than
                # ending the session, until the user approves it. That is not
                # a password retry -- a rejected password is still final.
                "TWOFA_TIMEOUT_ACTION": "restart",
                "RELOGIN_AFTER_TWOFA_TIMEOUT": "yes",
                "AUTO_RESTART_TIME": "11:59 PM",
                "TIME_ZONE": "America/New_York",
                "JAVA_HEAP_SIZE": "768",
            },
        )
        return name

    def restart(self, name: str) -> None:
        """Start a stopped gateway again: the same container, so the same login.

        The manager, not Docker, decides when: Docker's own restart policy
        would also restart a gateway that stopped on a rejected password.
        """
        self._client.containers.get(name).start()

    def remove(self, name: str) -> None:
        import docker.errors

        try:
            self._client.containers.get(name).remove(force=True)
        except docker.errors.NotFound:
            pass

    def info(self, name: str) -> GatewayInfo | None:
        import docker.errors

        try:
            container = self._client.containers.get(name)
        except docker.errors.NotFound:
            return None
        return _info(container)

    def logs(self, name: str, tail: int = 200) -> str:
        import docker.errors

        try:
            raw = self._client.containers.get(name).logs(tail=tail)
        except docker.errors.NotFound:
            return ""
        return raw.decode("utf-8", errors="replace")

    def running(self) -> list[GatewayInfo]:
        containers = self._client.containers.list(all=True, filters={"label": f"{LABEL}=gateway"})
        return [_info(c) for c in containers]


def _info(container: Any) -> GatewayInfo:
    labels = container.labels or {}
    return GatewayInfo(
        name=container.name,
        owner=labels.get(OWNER_LABEL, ""),
        ib_username=labels.get(USERNAME_LABEL, ""),
        trading_mode=labels.get(MODE_LABEL, "paper"),
        status=container.status,
    )
