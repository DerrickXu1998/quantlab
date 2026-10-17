"""The per-user gateway manager, against fake containers and collectors."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from quantlab_live import manager as manager_mod
from quantlab_live.docker_api import GatewayInfo, gateway_name
from quantlab_live.manager import Manager


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class FakeGateways:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, str, str]] = []
        self.containers: dict[str, GatewayInfo] = {}
        self.output: dict[str, str] = {}
        self.removed: list[str] = []

    def start(self, owner, username, password, mode):
        name = gateway_name(owner)
        self.started.append((owner, username, password, mode))
        self.containers[name] = GatewayInfo(name, owner, username, mode, "running")
        return name

    def remove(self, name):
        self.removed.append(name)
        self.containers.pop(name, None)

    def info(self, name):
        return self.containers.get(name)

    def logs(self, name, tail=200):
        return self.output.get(name, "")

    def running(self):
        return list(self.containers.values())

    def exit(self, owner):
        name = gateway_name(owner)
        info = self.containers[name]
        self.containers[name] = GatewayInfo(
            info.name, info.owner, info.ib_username, info.trading_mode, "exited"
        )


class FakeCollector:
    def __init__(self, owner, host, clock):
        self.owner, self.host = owner, host
        self.gateway = SimpleNamespace(connected=lambda: self.is_connected)
        self.is_connected = False
        self.last_lease_at = clock()
        self.stop_event = None

    async def run(self, stop):
        self.stop_event = stop
        await stop.wait()


@pytest.fixture
def world():
    clock = Clock()
    gateways = FakeGateways()
    collectors: dict[str, FakeCollector] = {}

    def make_collector(owner, host):
        collectors[owner] = FakeCollector(owner, host, clock)
        return collectors[owner]

    return (
        Manager(gateways, make_collector, max_gateways=2, clock=clock),
        gateways,
        collectors,
        clock,
    )


def run(coro):
    return asyncio.run(coro)


def scenario(fn):
    """Run an async test body in one loop (collector tasks need it)."""
    return asyncio.run(fn())


def test_two_gateways_run_and_the_third_user_queues(world):
    m, gateways, collectors, clock = world

    async def body():
        for user in ("a", "b", "c"):
            await m.connect(user, f"ib-{user}", f"pw-{user}", "paper")
        return m.view("a"), m.view("b"), m.view("c")

    a, b, c = scenario(body)
    assert a["state"] == b["state"] == "logging_in"
    assert c["state"] == "queued" and c["queue_position"] == 1
    assert [s[0] for s in gateways.started] == ["a", "b"]
    # Each gateway logs in as its own user, with its own password.
    assert ("a", "ib-a", "pw-a", "paper") in gateways.started


def test_a_freed_slot_goes_to_the_queue_and_passwords_leave_memory(world):
    m, gateways, collectors, clock = world

    async def body():
        for user in ("a", "b", "c"):
            await m.connect(user, f"ib-{user}", f"pw-{user}", "paper")
        assert m.sessions["c"].password == "pw-c"  # held only while queued
        assert m.sessions["a"].password is None  # already handed over
        await m.disconnect("a")
        return m.view("c")

    c = scenario(body)
    assert c["state"] == "logging_in"
    assert gateways.started[-1] == ("c", "ib-c", "pw-c", "paper")
    assert m.sessions["c"].password is None
    assert gateway_name("a") in gateways.removed
    assert all(s.password is None for s in m.sessions.values())


def test_a_queued_request_nobody_waits_for_is_dropped_with_its_password(world):
    m, gateways, collectors, clock = world

    async def body():
        for user in ("a", "b", "c"):
            await m.connect(user, f"ib-{user}", f"pw-{user}", "paper")
        clock.now += manager_mod.QUEUE_IDLE_SECONDS + 1
        # a and b are polled (their tabs are open); c's tab closed.
        m.view("a")
        m.view("b")
        await m.tick()

    scenario(body)
    assert "c" not in m.sessions
    assert m.view("c") == {"state": "none"}


def test_connected_when_the_gateway_api_answers(world):
    m, gateways, collectors, clock = world

    async def body():
        await m.connect("a", "ib-a", "pw", "paper")
        collectors["a"].is_connected = True
        await m.tick()
        return m.view("a")

    view = scenario(body)
    assert view["state"] == "connected"
    assert view["ib_username"] == "ib-a"
    assert collectors["a"].host == gateway_name("a")


def test_a_rejected_login_fails_once_and_is_never_retried(world):
    m, gateways, collectors, clock = world

    async def body():
        await m.connect("a", "ib-a", "wrong", "paper")
        gateways.output[gateway_name("a")] = "IBC: Login failed: Unrecognized Username or Password"
        clock.now += manager_mod.LOG_POLL_SECONDS
        await m.tick()
        await m.tick()
        return m.view("a")

    view = scenario(body)
    assert view["state"] == "failed"
    assert "rejected" in view["detail"]
    assert len(gateways.started) == 1  # no second attempt
    assert gateway_name("a") not in gateways.containers


def test_two_factor_is_surfaced_and_a_missed_prompt_fails(world):
    m, gateways, collectors, clock = world

    async def body():
        await m.connect("a", "ib-a", "pw", "live")
        gateways.output[gateway_name("a")] = "Second Factor Authentication initiated"
        clock.now += manager_mod.LOG_POLL_SECONDS
        await m.tick()
        waiting = m.view("a")
        gateways.exit("a")  # TWOFA_TIMEOUT_ACTION=exit
        await m.tick()
        return waiting, m.view("a")

    waiting, failed = scenario(body)
    assert waiting["state"] == "logging_in" and "IB Key" in waiting["detail"]
    assert failed["state"] == "failed" and "not approved in time" in failed["detail"]


def test_a_login_that_never_completes_times_out(world):
    m, gateways, collectors, clock = world

    async def body():
        await m.connect("a", "ib-a", "pw", "paper")
        clock.now += manager_mod.LOGIN_TIMEOUT_SECONDS + 1
        await m.tick()
        return m.view("a")

    assert scenario(body)["state"] == "failed"


def test_an_idle_gateway_is_stopped_and_frees_its_slot(world):
    m, gateways, collectors, clock = world

    async def body():
        await m.connect("a", "ib-a", "pw", "paper")
        await asyncio.sleep(0)  # let the collector task start
        collectors["a"].is_connected = True
        await m.tick()
        clock.now += manager_mod.IDLE_SECONDS + 1
        await m.tick()
        await asyncio.sleep(0)

    scenario(body)
    assert "a" not in m.sessions
    assert gateway_name("a") in gateways.removed
    assert collectors["a"].stop_event.is_set()


def test_reconnecting_with_the_same_login_does_not_log_in_twice(world):
    m, gateways, collectors, clock = world

    async def body():
        await m.connect("a", "ib-a", "pw", "paper")
        await m.connect("a", "ib-a", "pw", "paper")

    scenario(body)
    assert len(gateways.started) == 1


def test_a_restarted_manager_adopts_running_gateways(world):
    m, gateways, collectors, clock = world
    name = gateway_name("a")
    gateways.containers[name] = GatewayInfo(name, "a", "ib-a", "paper", "running")
    gateways.containers["dead"] = GatewayInfo("dead", "b", "ib-b", "paper", "exited")

    async def body():
        await m.adopt()
        return m.view("a")

    view = scenario(body)
    assert view["state"] == "logging_in" and view["ib_username"] == "ib-a"
    assert "dead" in gateways.removed
    assert "b" not in m.sessions
