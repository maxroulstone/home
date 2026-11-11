"""The real HA snapshot/event path delivers domain states without manual parsing."""

import asyncio

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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
