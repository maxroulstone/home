"""Real HA lux and availability events reach the registered domain-state handler."""

import asyncio

import pytest

from automation.ha.models import ServiceCall


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
ILLUMINANCE_INPUT = "input_number.simulation_lounge_illuminance"
AVAILABILITY_INPUT = "input_boolean.simulation_lounge_sensor_available"


async def test_snapshot_reports_initial_lux_sample(illuminance_states):
    async with asyncio.timeout(5):
        state = await illuminance_states.get()

    assert state is not None and state.available is True
    assert state.lux == 500
    assert state.measured_at is not None


@pytest.mark.parametrize("lux", [0, 1250, 2000])
async def test_lux_change_reaches_registered_handler(client, illuminance_states, lux):
    async with asyncio.timeout(5):
        before = await illuminance_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_number",
                service="set_value",
                entity_ids=(ILLUMINANCE_INPUT,),
                data={"value": lux},
            )
        )
        state = await illuminance_states.get()

    assert before is not None and before.measured_at is not None
    assert state is not None and state.available is True
    assert state.lux == lux
    assert state.measured_at is not None and state.measured_at > before.measured_at


async def test_unavailable_sensor_retains_last_lux_sample(client, illuminance_states):
    async with asyncio.timeout(5):
        before = await illuminance_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean",
                service="turn_off",
                entity_ids=(AVAILABILITY_INPUT,),
            )
        )
        unavailable = await illuminance_states.get()

    assert before is not None and before.measured_at is not None
    assert unavailable is not None and unavailable.available is False
    assert unavailable.lux == before.lux
    assert unavailable.measured_at == before.measured_at


async def test_availability_recovery_preserves_lux_sample_time(
    client, illuminance_states
):
    async with asyncio.timeout(5):
        before = await illuminance_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean",
                service="turn_off",
                entity_ids=(AVAILABILITY_INPUT,),
            )
        )
        await illuminance_states.get()
        await client.call_service(
            ServiceCall(
                domain="input_boolean",
                service="turn_on",
                entity_ids=(AVAILABILITY_INPUT,),
            )
        )
        recovered = await illuminance_states.get()

    assert before is not None and before.measured_at is not None
    assert recovered is not None and recovered.available is True
    assert recovered.lux == before.lux
    assert recovered.measured_at == before.measured_at
    assert recovered.updated_at > before.updated_at
