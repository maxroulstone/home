"""Small happy/sad path checks with a mocked WebSocket; no network access."""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from automation.ha.client import (
    AuthenticationError,
    HAClient,
    HAClientError,
    ProtocolError,
)
from automation.ha.models import EntityState


@pytest.fixture
def connection(monkeypatch):
    socket = AsyncMock()
    socket.recv.side_effect = [
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_ok"}),
    ]
    monkeypatch.setattr("automation.ha.client.connect", AsyncMock(return_value=socket))
    return HAClient("ws://localhost:8123/api/websocket", "test-token"), socket


def test_reads_states_twice_on_one_authenticated_connection(connection):
    client, socket = connection
    state = {
        "entity_id": "light.lounge",
        "state": "on",
        "attributes": {"brightness": 178},
        "last_changed": "2026-10-06T12:00:00Z",
        "last_updated": "2026-10-06T12:01:00Z",
    }
    socket.recv.side_effect = [
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_ok"}),
        json.dumps({"id": 1, "type": "result", "success": True, "result": [state]}),
        json.dumps({"id": 2, "type": "result", "success": True, "result": []}),
    ]

    async def scenario():
        async with client:
            assert await client.get_states() == [
                EntityState(
                    "light.lounge",
                    "on",
                    {"brightness": 178},
                    datetime(2026, 10, 6, 12, tzinfo=UTC),
                    datetime(2026, 10, 6, 12, 1, tzinfo=UTC),
                )
            ]
            assert await client.get_states() == []

    asyncio.run(scenario())
    assert [json.loads(call.args[0]) for call in socket.send.await_args_list] == [
        {"type": "auth", "access_token": "test-token"},
        {"id": 1, "type": "get_states"},
        {"id": 2, "type": "get_states"},
    ]
    socket.close.assert_awaited_once()


def test_second_request_waits_for_first_response(connection):
    """Hold the first response until the second read has attempted to start."""
    client, socket = connection

    async def scenario():
        first_waiting = asyncio.Event()
        release_first = asyncio.Event()
        second_started = asyncio.Event()
        request_ids = iter((1, 2))

        async def receive():
            request_id = next(request_ids)
            if request_id == 1:
                first_waiting.set()
                await release_first.wait()
            return json.dumps(
                {"id": request_id, "type": "result", "success": True, "result": []}
            )

        async def second_read():
            second_started.set()
            return await client.get_states()

        async with asyncio.timeout(1), client:
            socket.recv.side_effect = receive
            async with asyncio.TaskGroup() as tasks:
                first = tasks.create_task(client.get_states())
                await first_waiting.wait()
                second = tasks.create_task(second_read())
                await second_started.wait()

                # The second task has run, but only auth and request 1 were sent.
                assert socket.send.await_count == 2
                assert socket.recv.await_count == 3
                release_first.set()

            assert first.result() == second.result() == []

    asyncio.run(scenario())
    requests = [json.loads(call.args[0]) for call in socket.send.await_args_list][1:]
    assert requests == [
        {"id": 1, "type": "get_states"},
        {"id": 2, "type": "get_states"},
    ]


@pytest.mark.parametrize(
    "failure, expected",
    [
        (
            json.dumps({"type": "auth_invalid", "message": "test-token"}),
            AuthenticationError,
        ),
        (asyncio.CancelledError(), asyncio.CancelledError),
        (TimeoutError(), HAClientError),
    ],
)
def test_failed_entry_closes_connection(connection, failure, expected):
    client, socket = connection
    socket.recv.side_effect = [json.dumps({"type": "auth_required"}), failure]

    async def scenario():
        with pytest.raises(expected) as error:
            async with client:
                pytest.fail("Failed entry must not run the block")
        assert "test-token" not in str(error.value)

    asyncio.run(scenario())
    socket.close.assert_awaited_once()


def test_caller_error_still_closes_connection(connection):
    client, socket = connection

    async def scenario():
        with pytest.raises(ValueError, match="caller failed"):
            async with client:
                raise ValueError("caller failed")

    asyncio.run(scenario())
    socket.close.assert_awaited_once()


@pytest.mark.parametrize(
    "response, expected",
    [
        ({"id": 1, "type": "result", "success": False}, HAClientError),
        ({"id": 2, "type": "result", "success": True, "result": []}, ProtocolError),
    ],
)
def test_failed_request_raises_and_closes_on_exit(connection, response, expected):
    client, socket = connection
    socket.recv.side_effect = [
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_ok"}),
        json.dumps(response),
    ]

    async def scenario():
        with pytest.raises(expected):
            async with client:
                await client.get_states()

    asyncio.run(scenario())
    socket.close.assert_awaited_once()
