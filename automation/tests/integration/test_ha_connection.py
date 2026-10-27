"""Focused connection-manager checks against the local HA simulation."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
import pytest_asyncio

from automation.ha.client import HAClientError
from automation.ha.connection import HAConnectionManager
from automation.ha.models import EntityState, ServiceCall, StateChanged


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
PROBE = "input_boolean.simulation_probe"
TURN_ON = ServiceCall(domain="input_boolean", service="turn_on", entity_ids=(PROBE,))


@pytest_asyncio.fixture
async def connected_manager(
    manager: HAConnectionManager, snapshots: asyncio.Queue[list[EntityState]]
) -> HAConnectionManager:
    async with asyncio.timeout(20):
        await snapshots.get()
    await manager.call_service(
        ServiceCall(domain="input_boolean", service="turn_off", entity_ids=(PROBE,))
    )
    return manager


async def wait_for_probe(
    changes: asyncio.Queue[StateChanged], value: str
) -> StateChanged:
    async with asyncio.timeout(10):
        while True:
            change = await changes.get()
            if change.entity_id == PROBE and change.new_state:
                if change.new_state.state == value:
                    return change


async def test_connects_and_delivers_initial_snapshot(
    manager: HAConnectionManager, snapshots: asyncio.Queue[list[EntityState]]
):
    async with asyncio.timeout(20):
        states = await snapshots.get()
    assert any(state.entity_id == PROBE for state in states)


async def test_reconnects_after_ha_restarts(
    connected_manager: HAConnectionManager,
    snapshots: asyncio.Queue[list[EntityState]],
    stopped_simulation: Callable[[], AbstractAsyncContextManager[None]],
):
    async with stopped_simulation():
        pass

    async with asyncio.timeout(20):
        # A second snapshot is delivered only after a new connection is set up.
        await snapshots.get()


async def test_reconnect_refreshes_previous_state(
    connected_manager: HAConnectionManager,
    snapshots: asyncio.Queue[list[EntityState]],
    changes: asyncio.Queue[StateChanged],
    stopped_simulation: Callable[[], AbstractAsyncContextManager[None]],
):
    await connected_manager.call_service(TURN_ON)
    await wait_for_probe(changes, "on")

    async with stopped_simulation():
        pass

    async with asyncio.timeout(20):
        states = {state.entity_id: state for state in await snapshots.get()}
    # HA resets the helper to off. During startup it may still be absent from
    # the snapshot; either observation replaces the old on state.
    assert PROBE not in states or states[PROBE].state == "off"


async def test_receives_state_changes_after_reconnect(
    connected_manager: HAConnectionManager,
    snapshots: asyncio.Queue[list[EntityState]],
    changes: asyncio.Queue[StateChanged],
    stopped_simulation: Callable[[], AbstractAsyncContextManager[None]],
):
    async with stopped_simulation():
        pass
    async with asyncio.timeout(20):
        await snapshots.get()

    try:
        await connected_manager.call_service(TURN_ON)
        change = await wait_for_probe(changes, "on")
        assert change.old_state and change.old_state.state == "off"
    finally:
        await connected_manager.call_service(
            ServiceCall(domain="input_boolean", service="turn_off", entity_ids=(PROBE,))
        )


async def test_rejects_actions_while_disconnected(
    connected_manager: HAConnectionManager,
    disconnected: asyncio.Event,
    stopped_simulation: Callable[[], AbstractAsyncContextManager[None]],
):
    disconnected.clear()
    async with stopped_simulation():
        async with asyncio.timeout(10):
            await disconnected.wait()
        with pytest.raises(HAClientError, match="not ready"):
            await connected_manager.call_service(TURN_ON)
