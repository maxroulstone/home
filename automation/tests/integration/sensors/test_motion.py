"""Real HA motion events reach the registered domain-state handler."""

import asyncio

import pytest

from automation.ha.models import ServiceCall


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
MOTION_INPUT = "input_boolean.simulation_lounge_motion"
AVAILABILITY_INPUT = "input_boolean.simulation_lounge_sensor_available"


async def test_snapshot_reports_available_sensor_without_known_movement(motion_states):
    async with asyncio.timeout(5):
        state = await motion_states.get()

    assert state is not None and state.available is True
    assert state.last_motion_at is None


async def test_motion_report_reaches_registered_handler(client, motion_states):
    async with asyncio.timeout(5):
        await motion_states.get()  # Initial snapshot, before reporting movement.
        await client.call_service(
            ServiceCall(
                domain="input_boolean", service="turn_on", entity_ids=(MOTION_INPUT,)
            )
        )
        state = await motion_states.get()

    assert state is not None and state.available is True
    assert state.last_motion_at == state.updated_at


async def test_resetting_motion_signal_preserves_last_movement(client, motion_states):
    async with asyncio.timeout(5):
        await motion_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean", service="turn_on", entity_ids=(MOTION_INPUT,)
            )
        )
        movement = await motion_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean", service="turn_off", entity_ids=(MOTION_INPUT,)
            )
        )
        reset = await motion_states.get()

    assert movement is not None and movement.last_motion_at is not None
    assert reset is not None and reset.available is True
    assert reset.last_motion_at == movement.last_motion_at
    assert reset.updated_at > movement.updated_at


async def test_unavailable_sensor_retains_last_movement(client, motion_states):
    async with asyncio.timeout(5):
        await motion_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean", service="turn_on", entity_ids=(MOTION_INPUT,)
            )
        )
        movement = await motion_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean",
                service="turn_off",
                entity_ids=(AVAILABILITY_INPUT,),
            )
        )
        unavailable = await motion_states.get()

    assert movement is not None and movement.last_motion_at is not None
    assert unavailable is not None and unavailable.available is False
    assert unavailable.last_motion_at == movement.last_motion_at


async def test_availability_recovery_does_not_report_new_movement(
    client, motion_states
):
    async with asyncio.timeout(5):
        await motion_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean", service="turn_on", entity_ids=(MOTION_INPUT,)
            )
        )
        movement = await motion_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean",
                service="turn_off",
                entity_ids=(AVAILABILITY_INPUT,),
            )
        )
        await motion_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean",
                service="turn_on",
                entity_ids=(AVAILABILITY_INPUT,),
            )
        )
        recovered = await motion_states.get()

    assert movement is not None and movement.last_motion_at is not None
    assert recovered is not None and recovered.available is True
    assert recovered.last_motion_at == movement.last_motion_at
    assert recovered.updated_at > movement.updated_at
