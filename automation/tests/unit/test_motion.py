"""Movement reports do not require a corresponding motion-off report."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from automation.devices.motion import MotionState


REPORTED = datetime(2026, 10, 28, 12, tzinfo=UTC)


def test_unavailable_sensor_retains_last_movement_without_inventing_new_motion():
    state = MotionState(
        available=False,
        last_motion_at=REPORTED,
        updated_at=REPORTED + timedelta(minutes=5),
    )

    assert state.last_motion_at == REPORTED
    assert state.available is False


def test_no_known_movement_is_distinct_from_a_movement_report():
    state = MotionState(available=True, updated_at=REPORTED)

    assert state.last_motion_at is None


@pytest.mark.parametrize(
    "field, value",
    [
        ("last_motion_at", datetime(2026, 10, 28)),
        ("available", "true"),
        ("motion_stopped", True),
    ],
)
def test_invalid_motion_observations_are_rejected(field, value):
    with pytest.raises(ValidationError):
        MotionState.model_validate(
            {"available": True, "updated_at": REPORTED, field: value}
        )
