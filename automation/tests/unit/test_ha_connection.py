"""Connection recovery policy with fake clients and no real retry delays."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from automation.ha.client import (
    AuthenticationError,
    HAClient,
    HAClientError,
    ProtocolError,
)
from automation.ha.connection import HAConnectionManager
from automation.ha.models import EntityState, ServiceCall, StateChanged


def fake_client(states=()):
    client = MagicMock(spec=HAClient)
    client.__aenter__.return_value = client
    client.get_states.return_value = list(states)
    client.next_state_change.side_effect = HAClientError("Disconnected")
    return client


@pytest.mark.asyncio
async def test_reconnect_subscribes_and_refreshes_before_delivering_more_changes():
    state = EntityState(
        entity_id="light.lounge",
        state="on",
        attributes={},
        last_changed=datetime(2026, 10, 26, tzinfo=UTC),
        last_updated=datetime(2026, 10, 26, tzinfo=UTC),
    )
    change = StateChanged(
        entity_id=state.entity_id,
        old_state=None,
        new_state=state,
        time_fired=state.last_updated,
    )
    first, second = fake_client(), fake_client([state])
    first.next_state_change.side_effect = [change, HAClientError("Disconnected")]
    factory = MagicMock(side_effect=[first, second])
    sleep = AsyncMock()
    manager = HAConnectionManager(factory, sleep=sleep)
    delivered = []

    async def snapshot(states):
        delivered.append(states)
        if states:
            raise RuntimeError("Stop after recovery")

    async def event(value):
        delivered.append(value)

    with pytest.raises(RuntimeError, match="Stop after recovery"):
        await manager.run(snapshot, event)

    assert delivered == [[], change, [state]]
    for client in (first, second):
        assert client.method_calls[:2] == [
            call.subscribe_state_changes(),
            call.get_states(),
        ]
        client.__aexit__.assert_awaited_once()
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_failed_connections_back_off_to_cap_and_refresh_resets_delay():
    clients = [fake_client() for _ in range(7)]
    # Four failed entries, a refreshed session that drops, another failed entry,
    # then a successful session. The successful refresh resets the retry delay.
    for index in (0, 1, 2, 3, 5):
        clients[index].__aenter__.side_effect = HAClientError("Unavailable")
    sleep = AsyncMock()
    manager = HAConnectionManager(
        MagicMock(side_effect=clients), max_retry_delay=4, sleep=sleep
    )
    snapshot = AsyncMock(side_effect=[None, RuntimeError("Stop")])

    with pytest.raises(RuntimeError, match="Stop"):
        await manager.run(snapshot, AsyncMock())

    assert sleep.await_args_list == [call(n) for n in (1, 2, 4, 4, 1, 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["subscribe_state_changes", "get_states"])
async def test_failed_setup_closes_client_without_exposing_partial_state(operation):
    first, second = fake_client(), fake_client()
    getattr(first, operation).side_effect = HAClientError("Connection lost")
    sleep = AsyncMock()
    manager = HAConnectionManager(MagicMock(side_effect=[first, second]), sleep=sleep)
    snapshot = AsyncMock(side_effect=RuntimeError("Stop after recovery"))

    with pytest.raises(RuntimeError, match="Stop after recovery"):
        await manager.run(snapshot, AsyncMock())

    snapshot.assert_awaited_once_with([])
    first.__aexit__.assert_awaited_once()
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [AuthenticationError, ProtocolError])
async def test_invalid_authentication_or_protocol_is_not_retried(error):
    client = fake_client()
    client.subscribe_state_changes.side_effect = error("Invalid")
    sleep = AsyncMock()
    manager = HAConnectionManager(lambda: client, sleep=sleep)

    with pytest.raises(error):
        await manager.run(AsyncMock(), AsyncMock())

    client.__aexit__.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_calls_require_ready_connection_and_are_never_replayed():
    client = fake_client()
    client.call_service.side_effect = HAClientError("Reply lost")
    factory = MagicMock(return_value=client)
    manager = HAConnectionManager(factory)
    action = ServiceCall(
        domain="light", service="turn_on", entity_ids=("light.lounge",)
    )

    with pytest.raises(HAClientError, match="not ready"):
        await manager.call_service(action)

    async def snapshot(states):
        await manager.call_service(action)

    with pytest.raises(HAClientError, match="Reply lost"):
        await manager.run(snapshot, AsyncMock())

    factory.assert_called_once()
    client.call_service.assert_awaited_once_with(action)
    with pytest.raises(HAClientError, match="not ready"):
        await manager.call_service(action)


@pytest.mark.asyncio
@pytest.mark.parametrize("during_retry", [False, True])
async def test_cancellation_stops_waiting_and_closes_active_connection(during_retry):
    client = fake_client()
    waiting = asyncio.Event()

    async def wait(*args):
        waiting.set()
        await asyncio.Future()

    if not during_retry:
        client.next_state_change.side_effect = wait
    manager = HAConnectionManager(lambda: client, sleep=wait)

    async with asyncio.timeout(1):
        task = asyncio.create_task(manager.run(AsyncMock(), AsyncMock()))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    client.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_event_handler_errors_are_not_mistaken_for_connection_failures():
    client = fake_client()
    client.next_state_change.side_effect = None
    sleep = AsyncMock()
    manager = HAConnectionManager(lambda: client, sleep=sleep)

    with pytest.raises(HAClientError, match="Handler failed"):
        await manager.run(
            AsyncMock(), AsyncMock(side_effect=HAClientError("Handler failed"))
        )

    sleep.assert_not_awaited()
    client.__aexit__.assert_awaited_once()
