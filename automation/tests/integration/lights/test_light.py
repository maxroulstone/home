"""Each light control is checked against HA's actual reported virtual state."""

import asyncio

import pytest

from automation.devices.light import LightState
from automation.ha.adapters.light import HALight
from automation.ha.client import HAClient
from automation.ha.models import StateChanged


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
ENTITY_ID = "light.lounge"


async def reported_state(client: HAClient, light: HALight) -> LightState:
    entity = next(
        state for state in await client.get_states() if state.entity_id == ENTITY_ID
    )
    return light.parse_state(entity)


async def test_turn_on(light: HALight, client: HAClient):
    await light.turn_on()

    assert (await reported_state(client, light)).is_on is True


async def test_turn_off(light: HALight, client: HAClient):
    await light.turn_on()
    await light.turn_off()

    assert (await reported_state(client, light)).is_on is False


async def test_set_brightness(light: HALight, client: HAClient):
    await light.turn_on(brightness_pct=70)

    state = await reported_state(client, light)
    # Whole HA brightness values introduce less than 0.2 percentage points of rounding.
    assert state.brightness_pct == pytest.approx(70, abs=0.2)


async def test_set_colour_temperature(light: HALight, client: HAClient):
    await light.turn_on(color_temp_kelvin=2700)

    state = await reported_state(client, light)
    assert state.color_temp_kelvin == 2700


async def test_set_rgb_colour(light: HALight, client: HAClient):
    await light.turn_on(rgb_color=(255, 0, 128))

    state = await reported_state(client, light)
    assert state.rgb_color == (255, 0, 128)


async def test_reports_assumed_state(light: HALight, client: HAClient):
    state = await reported_state(client, light)

    assert state.assumed is True


async def test_translates_state_change_event(
    light: HALight, client: HAClient, changes: asyncio.Queue[StateChanged]
):
    before = await reported_state(client, light)
    await light.turn_on()

    async with asyncio.timeout(5):
        while True:
            event = await changes.get()
            if event.entity_id == ENTITY_ID:
                observation = light.parse_change(event)
                if observation.updated_at > before.updated_at:
                    break

    assert observation.is_on is True
