"""Vacuum observations distinguish unavailable, unknown, and reported activity."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from automation.devices.vacuum import VacuumState


UPDATED = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "activity, available",
    [
        ("cleaning", True),
        ("docked", True),
        ("error", True),
        ("unknown", True),
        ("unavailable", False),
    ],
)
def test_activity_determines_reported_availability(activity, available):
    state = VacuumState(activity=activity, updated_at=UPDATED)

    assert state.available is available
    assert state.battery_pct is None


def test_empty_battery_is_distinct_from_unknown_battery():
    state = VacuumState(activity="docked", updated_at=UPDATED, battery_pct=0)

    assert state.battery_pct == 0


@pytest.mark.parametrize(
    "field, value",
    [
        ("activity", "flying"),
        ("battery_pct", -1),
        ("battery_pct", 101),
        ("battery_pct", True),
        ("current_room", 3),
        ("current_room", ""),
        ("updated_at", datetime(2026, 10, 28)),
    ],
)
def test_invalid_vacuum_observations_are_rejected(field, value):
    with pytest.raises(ValidationError):
        VacuumState.model_validate(
            {"activity": "docked", "updated_at": UPDATED, field: value}
        )


def test_reported_current_room_uses_logical_identifier():
    state = VacuumState(activity="cleaning", updated_at=UPDATED, current_room="lounge")

    assert state.current_room == "lounge"


def test_missing_current_room_is_unknown():
    state = VacuumState(activity="cleaning", updated_at=UPDATED)

    assert state.current_room is None
