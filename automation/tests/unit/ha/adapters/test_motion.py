"""Movement evidence is distinct from attribute changes or sensor recovery."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from automation.devices.motion import MotionState
from automation.ha.adapters.motion import HAMotionSensor
from automation.ha.models import EntityState, StateChanged


REPORTED = datetime(2026, 10, 29, 12, tzinfo=UTC)
ENTITY_ID = "binary_sensor.lounge_motion_occupancy"


def entity(power="on", changed=0, updated=0, entity_id=ENTITY_ID):
    return EntityState(
        entity_id=entity_id,
        state=power,
        attributes={},
        last_changed=REPORTED + timedelta(seconds=changed),
        last_updated=REPORTED + timedelta(seconds=updated),
    )


@pytest.fixture
def sensor():
    return HAMotionSensor(entity_id=ENTITY_ID)


def test_initial_on_snapshot_uses_source_on_time_not_attribute_update_time(sensor):
    state = sensor.parse_state(entity(updated=5))

    assert state.last_motion_at == REPORTED
    assert state.updated_at == REPORTED + timedelta(seconds=5)


def test_reconnect_snapshot_keeps_known_motion_time(sensor):
    previous = MotionState(
        available=False, updated_at=REPORTED, last_motion_at=REPORTED
    )
    state = sensor.parse_state(entity(changed=10, updated=10), previous_state=previous)

    assert state.last_motion_at == REPORTED
    assert state.available is True


@pytest.mark.parametrize("old_power", [None, "off", "unknown", "on"])
def test_new_on_reports_include_repeated_forced_on(sensor, old_power):
    report = StateChanged(
        entity_id=ENTITY_ID,
        old_state=entity(old_power) if old_power is not None else None,
        new_state=entity(changed=5, updated=5),
        time_fired=REPORTED + timedelta(seconds=5),
    )

    assert sensor.parse_change(report).last_motion_at == REPORTED + timedelta(seconds=5)


def test_attribute_only_on_update_does_not_count_as_movement(sensor):
    report = StateChanged(
        entity_id=ENTITY_ID,
        old_state=entity(),
        new_state=entity(updated=5),
        time_fired=REPORTED + timedelta(seconds=5),
    )

    assert sensor.parse_change(report).last_motion_at == REPORTED


def test_recovery_from_unavailable_does_not_count_as_movement(sensor):
    previous = MotionState(
        available=False, updated_at=REPORTED, last_motion_at=REPORTED
    )
    report = StateChanged(
        entity_id=ENTITY_ID,
        old_state=entity("unavailable"),
        new_state=entity(changed=5, updated=5),
        time_fired=REPORTED + timedelta(seconds=5),
    )

    assert (
        sensor.parse_change(report, previous_state=previous).last_motion_at == REPORTED
    )


@pytest.mark.parametrize("power", ["off", "unknown", "unavailable", None])
def test_non_movement_reports_retain_last_motion_time(sensor, power):
    report = StateChanged(
        entity_id=ENTITY_ID,
        old_state=entity(),
        new_state=entity(power, changed=5, updated=5) if power is not None else None,
        time_fired=REPORTED + timedelta(seconds=5),
    )
    state = sensor.parse_change(report)

    assert state.last_motion_at == REPORTED
    assert state.available is (power not in (None, "unavailable"))


def test_unknown_snapshot_without_history_does_not_invent_motion(sensor):
    assert sensor.parse_state(entity("unknown")).last_motion_at is None


def test_invalid_binary_state_is_rejected(sensor):
    with pytest.raises(ValidationError):
        sensor.parse_state(entity("moving"))


def test_observation_for_another_sensor_is_rejected(sensor):
    with pytest.raises(ValueError, match="different motion sensor"):
        sensor.parse_state(entity(entity_id="binary_sensor.hallway_motion"))
