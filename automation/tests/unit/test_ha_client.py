"""Happy/sad path checks with a queued fake WebSocket; no network access."""

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
from automation.ha.models import EntityState, JSONValue, ServiceCall


class FakeSocket:
    """Receive blocks until a message arrives, like the real WebSocket."""

    def __init__(self):
        self.incoming: asyncio.Queue[dict[str, JSONValue] | BaseException] = (
            asyncio.Queue()
        )
        self.incoming.put_nowait({"type": "auth_required"})
        self.auth: dict[str, JSONValue] | BaseException = {"type": "auth_ok"}
        self.responses: dict[int, dict[str, JSONValue]] = {}
        self.send = AsyncMock(side_effect=self._send)
        self.recv = AsyncMock(side_effect=self._recv)
        self.close = AsyncMock()

    async def _send(self, payload):
        message = json.loads(payload)
        if message["type"] == "auth":
            self.incoming.put_nowait(self.auth)
        elif message["id"] in self.responses:
            self.incoming.put_nowait(self.responses[message["id"]])

    async def _recv(self):
        message = await self.incoming.get()
        if isinstance(message, BaseException):
            raise message
        return json.dumps(message)


def result(request_id: int, value: JSONValue = None) -> dict[str, JSONValue]:
    return {"id": request_id, "type": "result", "success": True, "result": value}


@pytest.fixture
def connection(monkeypatch):
    socket = FakeSocket()
    monkeypatch.setattr("automation.ha.client.connect", AsyncMock(return_value=socket))
    return HAClient("ws://localhost:8123/api/websocket", "test-token"), socket


def test_reads_states_twice_on_one_authenticated_connection(connection):
    client, socket = connection
    state: dict[str, JSONValue] = {
        "entity_id": "light.lounge",
        "state": "on",
        "attributes": {"brightness": 178},
        "last_changed": "2026-10-06T12:00:00Z",
        "last_updated": "2026-10-06T12:01:00Z",
    }
    socket.responses = {1: result(1, [state]), 2: result(2, [state])}

    async def scenario():
        async with client:
            first = await client.get_states()
            assert first == [
                EntityState(
                    "light.lounge",
                    "on",
                    {"brightness": 178},
                    datetime(2026, 10, 6, 12, tzinfo=UTC),
                    datetime(2026, 10, 6, 12, 1, tzinfo=UTC),
                )
            ]
            assert await client.get_states() == first

    asyncio.run(scenario())
    assert [json.loads(call.args[0]) for call in socket.send.await_args_list] == [
        {"type": "auth", "access_token": "test-token"},
        {"id": 1, "type": "get_states"},
        {"id": 2, "type": "get_states"},
    ]
    socket.close.assert_awaited_once()


def test_concurrent_reads_receive_their_own_out_of_order_responses(connection):
    client, socket = connection

    async def scenario():
        both_sent = asyncio.Event()
        original_send = socket.send.side_effect

        async def send(payload):
            await original_send(payload)
            if json.loads(payload).get("id") == 2:
                both_sent.set()

        socket.send.side_effect = send
        async with asyncio.timeout(1), client:
            async with asyncio.TaskGroup() as tasks:
                first = tasks.create_task(client.get_states())
                second = tasks.create_task(client.get_states())
                await both_sent.wait()
                assert not first.done() and not second.done()
                # An event can arrive between the request and its response.
                socket.incoming.put_nowait({"type": "event", "id": 99, "event": {}})
                socket.incoming.put_nowait(result(2, []))
                await second
                assert not first.done()
                socket.incoming.put_nowait(result(1, []))
            assert first.result() == second.result() == []
            assert client._events.get_nowait()["type"] == "event"

    asyncio.run(scenario())
    socket.close.assert_awaited_once()


@pytest.mark.parametrize(
    "failure, expected",
    [
        ({"type": "auth_invalid", "message": "test-token"}, AuthenticationError),
        (asyncio.CancelledError(), asyncio.CancelledError),
        (TimeoutError(), HAClientError),
    ],
)
def test_failed_entry_closes_connection(connection, failure, expected):
    client, socket = connection
    socket.auth = failure

    async def scenario():
        with pytest.raises(expected) as error:
            async with client:
                pytest.fail("Failed entry must not run the block")
        assert "test-token" not in str(error.value)

    asyncio.run(scenario())
    socket.close.assert_awaited_once()


def test_service_call_sends_target_and_data(connection):
    client, socket = connection
    socket.responses[1] = result(1, {"response": None})

    async def scenario():
        async with client:
            assert (
                await client.call_service(
                    ServiceCall(
                        "light", "turn_on", ("light.lounge",), {"brightness_pct": 70}
                    )
                )
                is None
            )

    asyncio.run(scenario())
    assert json.loads(socket.send.await_args.args[0]) == {
        "id": 1,
        "type": "call_service",
        "domain": "light",
        "service": "turn_on",
        "target": {"entity_id": ["light.lounge"]},
        "service_data": {"brightness_pct": 70},
    }


def test_rejected_service_call_raises(connection):
    client, socket = connection
    socket.responses[1] = {"id": 1, "type": "result", "success": False}

    async def scenario():
        async with client:
            with pytest.raises(HAClientError, match="HA rejected request"):
                await client.call_service(
                    ServiceCall("light", "turn_off", ("light.lounge",))
                )

    asyncio.run(scenario())


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
    socket.responses[1] = response

    async def scenario():
        with pytest.raises(expected):
            async with client:
                await client.get_states()

    asyncio.run(scenario())
    socket.close.assert_awaited_once()


def test_disconnect_fails_all_pending_requests(connection):
    client, socket = connection

    async def scenario():
        both_sent = asyncio.Event()
        original_send = socket.send.side_effect

        async def send(payload):
            await original_send(payload)
            if json.loads(payload).get("id") == 2:
                both_sent.set()

        socket.send.side_effect = send
        async with asyncio.timeout(1), client:
            first = asyncio.create_task(client.get_states())
            second = asyncio.create_task(client.get_states())
            await both_sent.wait()
            socket.incoming.put_nowait(OSError("private server details"))
            errors = await asyncio.gather(first, second, return_exceptions=True)
            assert all(isinstance(error, HAClientError) for error in errors)
            assert all(str(error) == "HA connection failed" for error in errors)

    asyncio.run(scenario())
    socket.close.assert_awaited_once()


def test_cancelled_read_does_not_poison_the_next_response(connection):
    client, socket = connection

    async def scenario():
        sent = asyncio.Event()
        original_send = socket.send.side_effect

        async def send(payload):
            await original_send(payload)
            sent.set()

        async with asyncio.timeout(1), client:
            socket.send.side_effect = send
            first = asyncio.create_task(client.get_states())
            await sent.wait()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            socket.close.assert_not_awaited()
            # The late result for request 1 must not satisfy request 2.
            socket.incoming.put_nowait(result(1, None))
            socket.responses[2] = result(2, [])
            assert await client.get_states() == []

    asyncio.run(scenario())
    socket.close.assert_awaited_once()


def state_change_message(
    old: str | None = "off", new: str | None = "on"
) -> dict[str, JSONValue]:
    def state(value: str | None) -> JSONValue:
        if value is None:
            return None
        return {
            "entity_id": "light.lounge",
            "state": value,
            "attributes": {},
            "last_changed": "2026-10-25T12:00:00Z",
            "last_updated": "2026-10-25T12:00:00Z",
        }

    return {
        "id": 1,
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "time_fired": "2026-10-25T12:00:00Z",
            "data": {
                "entity_id": "light.lounge",
                "old_state": state(old),
                "new_state": state(new),
            },
        },
    }


@pytest.mark.parametrize("old, new", [("off", "on"), (None, "on"), ("on", None)])
def test_subscribes_and_reads_typed_state_changes(connection, old, new):
    client, socket = connection
    socket.responses = {1: result(1), 2: result(2, [])}
    original_send = socket.send.side_effect

    async def send(payload):
        if json.loads(payload)["type"] == "subscribe_events":
            # Events arriving before subscribe returns must be retained.
            socket.incoming.put_nowait(state_change_message(old, new))
        await original_send(payload)

    socket.send.side_effect = send

    async def scenario():
        async with asyncio.timeout(1), client:
            await client.subscribe_state_changes()
            await client.subscribe_state_changes()  # No duplicate subscription.
            assert await client.get_states() == []  # Commands still work.
            change = await client.next_state_change()
            assert change.entity_id == "light.lounge"
            assert (change.old_state.state if change.old_state else None) == old
            assert (change.new_state.state if change.new_state else None) == new
            assert change.time_fired == datetime(2026, 10, 25, 12, tzinfo=UTC)

    asyncio.run(scenario())
    assert json.loads(socket.send.await_args_list[1].args[0]) == {
        "id": 1,
        "type": "subscribe_events",
        "event_type": "state_changed",
    }
    assert socket.send.await_count == 3  # Auth, subscribe, get_states.


def test_rejected_subscription_raises(connection):
    client, socket = connection
    socket.responses[1] = {"id": 1, "type": "result", "success": False}

    async def scenario():
        async with client:
            with pytest.raises(HAClientError, match="HA rejected request"):
                await client.subscribe_state_changes()

    asyncio.run(scenario())
    socket.close.assert_awaited_once()


@pytest.mark.parametrize("disconnect", [False, True])
def test_unsubscribe_or_disconnect_wakes_waiting_event_consumer(connection, disconnect):
    client, socket = connection
    socket.responses = {1: result(1), 2: result(2, True)}

    async def scenario():
        waiting = asyncio.Event()

        async def consume():
            waiting.set()
            return await client.next_state_change()

        async with asyncio.timeout(1), client:
            await client.subscribe_state_changes()
            consumer = asyncio.create_task(consume())
            await waiting.wait()
            if disconnect:
                socket.incoming.put_nowait(OSError("private server details"))
            else:
                await client.unsubscribe_state_changes()
                assert json.loads(socket.send.await_args.args[0]) == {
                    "id": 2,
                    "type": "unsubscribe_events",
                    "subscription": 1,
                }
            with pytest.raises(HAClientError, match="stream closed"):
                await consumer

    asyncio.run(scenario())


def test_malformed_state_change_is_rejected(connection):
    client, socket = connection
    socket.responses[1] = result(1)

    async def scenario():
        async with asyncio.timeout(1), client:
            await client.subscribe_state_changes()
            socket.incoming.put_nowait({"id": 1, "type": "event", "event": {}})
            with pytest.raises(ProtocolError, match="Invalid state-change"):
                await client.next_state_change()

    asyncio.run(scenario())
