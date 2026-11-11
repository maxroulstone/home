"""Reported light observations are validated independently of action requests."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from automation.devices.light import LightState
from automation.ha.adapters.light import HALight
from automation.ha.models import EntityState, StateChanged
from automation.ha.protocols import HAServiceCaller


UPDATED = datetime(2026, 10, 27, 12, tzinfo=UTC)


@pytest.fixture
def entity_data():
    return {
        "entity_id": "light.lounge",
        "state": "on",
        "last_changed": UPDATED,
        "last_updated": UPDATED,
        "attributes": {
            "brightness": 128,
            "color_temp_kelvin": 2700,
            "rgb_color": [255, 0, 128],
            "assumed_state": True,
        },
    }


@pytest.fixture
def light():
    return HALight(MagicMock(spec_set=HAServiceCaller), entity_id="light.lounge")


def test_translates_reported_attributes_and_preserves_source_timestamp(
    light, entity_data
):
    state = light.parse_state(EntityState.model_validate(entity_data))

    assert state == LightState(
        power="on",
        updated_at=UPDATED,
        brightness_pct=128 * 100 / 255,
        color_temp_kelvin=2700,
        rgb_color=(255, 0, 128),
        assumed=True,
    )


@pytest.mark.parametrize(
    "power, is_on, available",
    [
        ("on", True, True),
        ("off", False, True),
        ("unknown", None, True),
        ("unavailable", None, False),
    ],
)
def test_power_status_does_not_treat_missing_knowledge_as_off(
    light, entity_data, power, is_on, available
):
    state = light.parse_state(
        EntityState.model_validate({**entity_data, "state": power})
    )

    assert state.is_on is is_on
    assert state.available is available


def test_missing_attributes_remain_unknown(light, entity_data):
    state = light.parse_state(
        EntityState.model_validate({**entity_data, "attributes": {}})
    )

    assert state.brightness_pct is None
    assert state.color_temp_kelvin is None
    assert state.rgb_color is None


@pytest.mark.parametrize(
    "attribute, value",
    [
        ("brightness", 256),
        ("brightness", True),
        ("rgb_color", [255, 0]),
        ("assumed_state", "true"),
    ],
)
def test_invalid_reported_attributes_are_rejected(light, entity_data, attribute, value):
    entity_data["attributes"][attribute] = value

    with pytest.raises(ValidationError):
        light.parse_state(EntityState.model_validate(entity_data))


def test_observation_for_another_entity_is_rejected(light, entity_data):
    entity = EntityState.model_validate({**entity_data, "entity_id": "light.hallway"})

    with pytest.raises(ValueError, match="different light"):
        light.parse_state(entity)


def test_state_change_translates_new_observation(light, entity_data):
    entity = EntityState.model_validate(entity_data)
    change = StateChanged(
        entity_id=entity.entity_id, old_state=None, new_state=entity, time_fired=UPDATED
    )

    assert light.parse_change(change) == light.parse_state(entity)


def test_removed_entity_is_reported_as_unavailable(light, entity_data):
    change = StateChanged(
        entity_id="light.lounge",
        old_state=EntityState.model_validate(entity_data),
        new_state=None,
        time_fired=UPDATED,
    )

    assert light.parse_change(change) == LightState(
        power="unavailable", updated_at=UPDATED
    )
