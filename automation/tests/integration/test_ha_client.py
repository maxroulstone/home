"""Focused checks against real local HA; no physical devices involved."""

import asyncio
from collections.abc import Callable

import pytest

from automation.ha.client import HAClient
from automation.ha.models import ServiceCall


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_connect_and_authenticate(client_factory: Callable[[], HAClient]):
    # Entering and exiting successfully is the assertion here.
    async with client_factory():
        pass


async def test_get_states(client: HAClient):
    states = await client.get_states()
    assert any(state.entity_id == "input_boolean.simulation_probe" for state in states)


async def test_service_call_changes_reported_state(client: HAClient, probe: str):
    await client.call_service(
        ServiceCall(domain="input_boolean", service="turn_on", entity_ids=(probe,))
    )
    states = {state.entity_id: state for state in await client.get_states()}
    assert states[probe].state == "on"


async def test_subscription_receives_state_change(client: HAClient, probe: str):
    await client.subscribe_state_changes()
    try:
        await client.call_service(
            ServiceCall(domain="input_boolean", service="turn_on", entity_ids=(probe,))
        )
        async with asyncio.timeout(5):
            while True:
                change = await client.next_state_change()
                if change.entity_id == probe:
                    break
        assert change.old_state and change.old_state.state == "off"
        assert change.new_state and change.new_state.state == "on"
    finally:
        await client.unsubscribe_state_changes()
