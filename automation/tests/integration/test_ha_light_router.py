"""The real HA snapshot/event path delivers domain states without manual parsing."""

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio

from automation.devices.light import LightState
from automation.ha.adapters.light import HALight
from automation.ha.client import HAClient
from automation.ha.connection import HAConnectionManager
from automation.ha.models import ServiceCall
from automation.ha.routing.lights import HALightRouter


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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


async def test_snapshot_reaches_registered_handler(routed_light):
    _, states = routed_light
    async with asyncio.timeout(10):
        state = await states.get()

    assert state is not None and state.is_on is False


async def test_light_command_result_arrives_as_routed_state_change(routed_light):
    light, states = routed_light
    async with asyncio.timeout(10):
        await states.get()  # Initial snapshot makes the manager ready for commands.
        await light.turn_on()
        state = await states.get()

    assert state is not None and state.is_on is True
