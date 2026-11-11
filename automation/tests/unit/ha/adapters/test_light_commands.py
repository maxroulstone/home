"""Light requests translate to HA calls without touching a real connection."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from automation.devices.light import Light, LightCommandError
from automation.ha.adapters.light import HALight
from automation.ha.client import HAClientError
from automation.ha.models import EntityState, ServiceCall
from automation.ha.protocols import HAServiceCaller


pytestmark = pytest.mark.asyncio


@pytest.fixture
def service_caller():
    return MagicMock(spec_set=HAServiceCaller)


@pytest.fixture
def light(service_caller) -> Light:
    return HALight(service_caller, entity_id="light.lounge")


@pytest.mark.parametrize("brightness", [0, 70, 100])
async def test_turn_on_sends_brightness_to_configured_entity(
    light, service_caller, brightness
):
    await light.turn_on(brightness_pct=brightness)

    service_caller.call_service.assert_awaited_once_with(
        ServiceCall(
            domain="light",
            service="turn_on",
            entity_ids=("light.lounge",),
            data={"brightness_pct": brightness},
        )
    )


async def test_turn_off_sends_no_brightness(light, service_caller):
    await light.turn_off()

    service_caller.call_service.assert_awaited_once_with(
        ServiceCall(domain="light", service="turn_off", entity_ids=("light.lounge",))
    )


async def test_turn_on_without_options_sends_empty_data(light, service_caller):
    await light.turn_on()

    service_caller.call_service.assert_awaited_once_with(
        ServiceCall(domain="light", service="turn_on", entity_ids=("light.lounge",))
    )


async def test_turn_on_sends_kelvin_with_brightness(light, service_caller):
    await light.turn_on(brightness_pct=70, color_temp_kelvin=2700)

    service_caller.call_service.assert_awaited_once_with(
        ServiceCall(
            domain="light",
            service="turn_on",
            entity_ids=("light.lounge",),
            data={"brightness_pct": 70, "color_temp_kelvin": 2700},
        )
    )


async def test_turn_on_sends_rgb_as_json_list_without_brightness(light, service_caller):
    await light.turn_on(rgb_color=(255, 0, 128))

    service_caller.call_service.assert_awaited_once_with(
        ServiceCall(
            domain="light",
            service="turn_on",
            entity_ids=("light.lounge",),
            data={"rgb_color": [255, 0, 128]},
        )
    )


@pytest.mark.parametrize("kelvin", [0, "2700"])
async def test_invalid_kelvin_is_rejected_before_sending(light, service_caller, kelvin):
    with pytest.raises(ValidationError):
        await light.turn_on(color_temp_kelvin=kelvin)

    service_caller.call_service.assert_not_awaited()


@pytest.mark.parametrize("rgb", [(-1, 0, 0), (256, 0, 0), (255, 0), (True, 0, 0)])
async def test_invalid_rgb_is_rejected_before_sending(light, service_caller, rgb):
    with pytest.raises(ValidationError):
        await light.turn_on(rgb_color=rgb)

    service_caller.call_service.assert_not_awaited()


async def test_conflicting_colour_modes_are_rejected_before_sending(
    light, service_caller
):
    with pytest.raises(ValueError, match="not both"):
        await light.turn_on(color_temp_kelvin=2700, rgb_color=(255, 0, 0))

    service_caller.call_service.assert_not_awaited()


@pytest.mark.parametrize("brightness", [-1, 101, True, "70"])
async def test_invalid_brightness_is_rejected_before_sending(
    light, service_caller, brightness
):
    with pytest.raises(ValidationError):
        await light.turn_on(brightness_pct=brightness)

    service_caller.call_service.assert_not_awaited()


@pytest.mark.parametrize("service", ["turn_on", "turn_off"])
async def test_ha_failure_becomes_device_error_without_retry(
    light, service_caller, service
):
    service_caller.call_service.side_effect = HAClientError(
        "HA connection is not ready"
    )

    with pytest.raises(LightCommandError, match="could not be confirmed"):
        if service == "turn_on":
            await light.turn_on(brightness_pct=70)
        else:
            await light.turn_off()

    assert service_caller.call_service.await_count == 1


async def test_request_does_not_change_reported_observation(service_caller):
    light = HALight(service_caller, entity_id="light.lounge")
    observation = light.parse_state(
        EntityState(
            entity_id="light.lounge",
            state="off",
            attributes={},
            last_changed=datetime(2026, 10, 27, tzinfo=UTC),
            last_updated=datetime(2026, 10, 27, tzinfo=UTC),
        )
    )
    await light.turn_on(brightness_pct=70)

    assert observation.is_on is False
