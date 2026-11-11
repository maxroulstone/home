"""Reset local sensor inputs and route real HA observations for each test."""

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio

from automation.devices.illuminance import IlluminanceState
from automation.devices.motion import MotionState
from automation.ha.adapters.illuminance import HAIlluminanceSensor
from automation.ha.adapters.motion import HAMotionSensor
from automation.ha.client import HAClient
from automation.ha.connection import HAConnectionManager
from automation.ha.models import EntityState, ServiceCall, StateChanged
from automation.ha.routing.illuminance import HAIlluminanceRouter
from automation.ha.routing.motion import HAMotionRouter


@pytest.fixture
def motion_states() -> asyncio.Queue[MotionState | None]:
    return asyncio.Queue()


@pytest.fixture
def illuminance_states() -> asyncio.Queue[IlluminanceState | None]:
    return asyncio.Queue()


@pytest_asyncio.fixture(autouse=True)
async def sensor_connection(
    client: HAClient,
    client_factory: Callable[[], HAClient],
    motion_states: asyncio.Queue[MotionState | None],
    illuminance_states: asyncio.Queue[IlluminanceState | None],
) -> AsyncIterator[None]:
    async def reset_inputs() -> None:
        await client.call_service(
            ServiceCall(
                domain="input_boolean",
                service="turn_off",
                entity_ids=("input_boolean.simulation_lounge_motion",),
            )
        )
        await client.call_service(
            ServiceCall(
                domain="input_number",
                service="set_value",
                entity_ids=("input_number.simulation_lounge_illuminance",),
                data={"value": 500},
            )
        )
        await client.call_service(
            ServiceCall(
                domain="input_boolean",
                service="turn_on",
                entity_ids=("input_boolean.simulation_lounge_sensor_available",),
            )
        )
        # Template updates may follow the helper service acknowledgement.
        async with asyncio.timeout(5):
            while True:
                states = {state.entity_id: state for state in await client.get_states()}
                motion = states.get("binary_sensor.lounge_motion_occupancy")
                illuminance = states.get("sensor.lounge_motion_illuminance")
                if (
                    motion is not None
                    and motion.state == "off"
                    and illuminance is not None
                    and illuminance.state not in ("unknown", "unavailable")
                    and float(illuminance.state) == 500
                ):
                    return
                await asyncio.sleep(0.05)

    motion_router = HAMotionRouter()
    motion_router.register(
        HAMotionSensor(entity_id="binary_sensor.lounge_motion_occupancy"),
        on_state_received=motion_states.put,
    )
    illuminance_router = HAIlluminanceRouter()
    illuminance_router.register(
        HAIlluminanceSensor(entity_id="sensor.lounge_motion_illuminance"),
        on_state_received=illuminance_states.put,
    )

    async def handle_state_snapshot(states: list[EntityState]) -> None:
        await motion_router.handle_state_snapshot(states)
        await illuminance_router.handle_state_snapshot(states)

    async def handle_state_change(change: StateChanged) -> None:
        await motion_router.handle_state_change(change)
        await illuminance_router.handle_state_change(change)

    try:
        await reset_inputs()
        manager = HAConnectionManager(client_factory)
        async with asyncio.TaskGroup() as tasks:
            running = tasks.create_task(
                manager.run(handle_state_snapshot, handle_state_change)
            )
            try:
                yield
            finally:
                running.cancel()
    finally:
        await reset_inputs()
