"""Lux conversion preserves evidence of sample freshness across availability changes."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from automation.devices.illuminance import IlluminanceState
from automation.ha.adapters.illuminance import HAIlluminanceSensor
from automation.ha.models import EntityState, StateChanged


MEASURED = datetime(2026, 10, 29, 12, tzinfo=UTC)
ENTITY_ID = "sensor.lounge_motion_illuminance"


def entity(value="100", changed=0, updated=0, unit="lx", entity_id=ENTITY_ID):
    return EntityState(
        entity_id=entity_id,
        state=value,
        attributes={"unit_of_measurement": unit},
        last_changed=MEASURED + timedelta(seconds=changed),
        last_updated=MEASURED + timedelta(seconds=updated),
    )


@pytest.fixture
def sensor():
    return HAIlluminanceSensor(entity_id=ENTITY_ID)


@pytest.mark.parametrize("value, lux", [("0", 0), ("123.5", 123.5)])
def test_numeric_state_is_converted_to_lux_with_source_sample_time(sensor, value, lux):
    state = sensor.parse_state(entity(value, updated=5))

    assert state.lux == lux
    assert state.measured_at == MEASURED
    assert state.updated_at == MEASURED + timedelta(seconds=5)


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "bright"])
def test_invalid_lux_readings_are_rejected(sensor, value):
    with pytest.raises(ValidationError):
        sensor.parse_state(entity(value))


def test_incompatible_unit_is_rejected(sensor):
    with pytest.raises(ValidationError):
        sensor.parse_state(entity(unit="%"))


def test_attribute_change_does_not_make_same_lux_reading_fresh(sensor):
    report = StateChanged(
        entity_id=ENTITY_ID,
        old_state=entity(),
        new_state=entity(updated=5),
        time_fired=MEASURED + timedelta(seconds=5),
    )

    assert sensor.parse_change(report).measured_at == MEASURED


def test_repeated_forced_numeric_report_updates_sample_time(sensor):
    report = StateChanged(
        entity_id=ENTITY_ID,
        old_state=entity(),
        new_state=entity(changed=5, updated=5),
        time_fired=MEASURED + timedelta(seconds=5),
    )

    assert sensor.parse_change(report).measured_at == MEASURED + timedelta(seconds=5)


def test_snapshot_does_not_refresh_known_sample_time(sensor):
    previous = IlluminanceState(
        available=True, updated_at=MEASURED, lux=100, measured_at=MEASURED
    )
    state = sensor.parse_state(entity(changed=5, updated=5), previous_state=previous)

    assert state.measured_at == MEASURED


@pytest.mark.parametrize("value", ["unknown", "unavailable", None])
def test_unavailable_or_removed_sensor_keeps_last_known_sample(sensor, value):
    report = StateChanged(
        entity_id=ENTITY_ID,
        old_state=entity(),
        new_state=entity(value, changed=5, updated=5) if value is not None else None,
        time_fired=MEASURED + timedelta(seconds=5),
    )
    state = sensor.parse_change(report)

    assert state.lux == 100
    assert state.measured_at == MEASURED
    assert state.available is (value not in (None, "unavailable"))


def test_availability_recovery_does_not_refresh_same_cached_sample(sensor):
    previous = IlluminanceState(
        available=False, updated_at=MEASURED, lux=100, measured_at=MEASURED
    )
    report = StateChanged(
        entity_id=ENTITY_ID,
        old_state=entity("unavailable"),
        new_state=entity(changed=5, updated=5),
        time_fired=MEASURED + timedelta(seconds=5),
    )

    assert sensor.parse_change(report, previous_state=previous).measured_at == MEASURED


def test_missing_initial_reading_stays_unknown(sensor):
    state = sensor.parse_state(entity("unknown"))

    assert state.lux is None
    assert state.measured_at is None


def test_observation_for_another_sensor_is_rejected(sensor):
    with pytest.raises(ValueError, match="different illuminance sensor"):
        sensor.parse_state(entity(entity_id="sensor.hallway_illuminance"))
