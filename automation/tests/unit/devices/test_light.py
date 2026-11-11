"""Validation of integration-independent light state."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from automation.devices.light import LightState


UPDATED = datetime(2026, 10, 27, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "field, value",
    [
        ("power", "maybe"),
        ("updated_at", datetime(2026, 10, 27)),
        ("brightness_pct", 101),
    ],
)
def test_domain_state_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError):
        LightState.model_validate({"power": "on", "updated_at": UPDATED, field: value})
