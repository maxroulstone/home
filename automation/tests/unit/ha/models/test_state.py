"""Validate HA entity fields and source timestamps."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from automation.ha.models import EntityState


@pytest.fixture
def state_data():
    return {
        "entity_id": "light.lounge",
        "state": "on",
        "attributes": {"brightness": 178},
        "last_changed": "2026-10-25T12:00:00Z",
        "last_updated": "2026-10-25T12:00:00Z",
    }


def test_entity_parses_timestamps_and_ignores_extra_ha_metadata(state_data):
    state = EntityState.model_validate({**state_data, "context": {"id": "ha-context"}})
    assert state.last_updated == datetime(2026, 10, 25, 12, tzinfo=UTC)
    assert state.attributes == {"brightness": 178}
    assert "context" not in state.model_dump()


@pytest.mark.parametrize(
    "field, value",
    [
        ("state", True),
        ("attributes", []),
        ("last_changed", "2026-10-25T12:00:00"),  # No timezone.
        ("last_updated", 1234567890),  # Don't silently convert epoch numbers.
    ],
)
def test_entity_rejects_invalid_fields(state_data, field, value):
    with pytest.raises(ValidationError):
        EntityState.model_validate({**state_data, field: value})
