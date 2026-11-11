"""Known virtual-light state and live routed observations for light tests."""

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio

from automation.devices.light import LightState
from automation.ha.adapters.light import HALight
from automation.ha.client import HAClient
from automation.ha.connection import HAConnectionManager
from automation.ha.models import EntityState, ServiceCall
from automation.ha.routing.lights import HALightRouter


ENTITY_ID = "light.lounge"


@pytest_asyncio.fixture
async def light(
    manager: HAConnectionManager,
    snapshots: asyncio.Queue[list[EntityState]],
) -> AsyncIterator[HALight]:
    async with asyncio.timeout(20):
        states = await snapshots.get()
    if not any(state.entity_id == ENTITY_ID for state in states):
        pytest.fail(
            "Virtual light missing; restart the simulation with its updated config"
        )

    device = HALight(manager, entity_id=ENTITY_ID)
    # Start each test off with known brightness and colour, independent of order.
    await device.turn_on(brightness_pct=100, color_temp_kelvin=4000)
    await device.turn_off()
    try:
        yield device
    finally:
        await device.turn_off()


@pytest_asyncio.fixture
async def routed_light(
    client: HAClient,
    client_factory: Callable[[], HAClient],
) -> AsyncIterator[tuple[HALight, asyncio.Queue[LightState | None]]]:
    off = ServiceCall(domain="light", service="turn_off", entity_ids=("light.lounge",))
    await client.call_service(off)
    states: asyncio.Queue[LightState | None] = asyncio.Queue()
    manager = HAConnectionManager(client_factory)
    light = HALight(manager, entity_id="light.lounge")
    router = HALightRouter()
    router.register(light, on_state_received=states.put)

    async with asyncio.TaskGroup() as tasks:
        running = tasks.create_task(
            manager.run(router.handle_state_snapshot, router.handle_state_change)
        )
        try:
            yield light, states
        finally:
            running.cancel()
            await client.call_service(off)
