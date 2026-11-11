"""A measured lux sample retains its own freshness and accepts darkness."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from automation.devices.illuminance import IlluminanceState


MEASURED = datetime(2026, 10, 28, 12, tzinfo=UTC)


def test_zero_lux_keeps_its_measurement_time_after_availability_changes():
    state = IlluminanceState(
        available=False,
        lux=0,
        measured_at=MEASURED,
        updated_at=MEASURED + timedelta(minutes=10),
    )

    assert state.lux == 0
    assert state.measured_at == MEASURED


def test_absent_reading_is_unknown():
    state = IlluminanceState(available=True, updated_at=MEASURED)

    assert state.lux is None
    assert state.measured_at is None


@pytest.mark.parametrize("lux", [-1, float("nan"), float("inf"), True, "100"])
def test_invalid_lux_is_rejected(lux):
    with pytest.raises(ValidationError):
        IlluminanceState(
            available=True,
            updated_at=MEASURED,
            measured_at=MEASURED,
            lux=lux,
        )


@pytest.mark.parametrize("measurement", [{"lux": 100}, {"measured_at": MEASURED}])
def test_reading_and_measurement_time_must_be_supplied_together(measurement):
    with pytest.raises(ValidationError):
        IlluminanceState.model_validate(
            {
                "available": True,
                "updated_at": MEASURED,
                **measurement,
            }
        )
