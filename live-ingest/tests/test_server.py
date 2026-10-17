"""The manager's internal HTTP API: token required, password never echoed."""

from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from quantlab_live.server import make_app

TOKEN = "s3cret-token"
PASSWORD = "do-not-echo-me"


class FakeManager:
    def __init__(self) -> None:
        self.connected: list[tuple] = []

    def view(self, owner):
        return {"state": "none"}

    async def connect(self, owner, username, password, mode):
        self.connected.append((owner, username, password, mode))
        return {"state": "queued", "ib_username": username, "queue_position": 1}

    async def disconnect(self, owner):
        return {"state": "none"}


def with_client(fn):
    async def body():
        manager = FakeManager()
        async with TestClient(TestServer(make_app(manager, TOKEN))) as client:
            return await fn(client, manager)

    return asyncio.run(body())


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_every_session_call_needs_the_token():
    async def fn(client, manager):
        statuses = [
            (await client.get("/sessions/u1")).status,
            (
                await client.post("/sessions/u1", json={"username": "x", "password": PASSWORD})
            ).status,
            (await client.delete("/sessions/u1", headers={"Authorization": "Bearer nope"})).status,
            (await client.get("/healthz")).status,
        ]
        return statuses, manager.connected

    statuses, connected = with_client(fn)
    assert statuses == [401, 401, 401, 200]
    assert connected == []


def test_connect_hands_the_password_on_and_never_returns_it():
    async def fn(client, manager):
        response = await client.post(
            "/sessions/u1",
            json={"username": "ib-u1", "password": PASSWORD, "trading_mode": "live"},
            headers=AUTH,
        )
        return response.status, await response.text(), manager.connected

    status, text, connected = with_client(fn)
    assert status == 202
    assert PASSWORD not in text
    assert connected == [("u1", "ib-u1", PASSWORD, "live")]


def test_bad_bodies_are_refused_without_echo():
    async def fn(client, manager):
        out = []
        for body in (
            {"password": PASSWORD},
            {"username": "x", "password": PASSWORD, "trading_mode": "margin"},
        ):
            response = await client.post("/sessions/u1", json=body, headers=AUTH)
            out.append((response.status, await response.text()))
        return out, manager.connected

    results, connected = with_client(fn)
    assert [status for status, _ in results] == [400, 400]
    assert all(PASSWORD not in text for _, text in results)
    assert connected == []
