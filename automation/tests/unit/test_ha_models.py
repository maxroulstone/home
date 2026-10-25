"""Validation at the HA boundary, including strict types and aware timestamps."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from automation.ha.messages import MESSAGE_ADAPTER, CommandResponse
from automation.ha.models import EntityState, ServiceCall


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


@pytest.mark.parametrize(
    "field, value",
    [
        ("id", True),
        ("id", "1"),
        ("success", "true"),
    ],
)
def test_command_response_rejects_coercible_types(field, value):
    message = {"type": "result", "id": 1, "success": True, field: value}
    with pytest.raises(ValidationError):
        MESSAGE_ADAPTER.validate_json(json.dumps(message))


def test_response_id_is_available_as_a_validated_integer():
    message = MESSAGE_ADAPTER.validate_json(
        '{"type":"result","id":1,"success":true,"result":null}'
    )
    assert isinstance(message, CommandResponse)
    assert message.id == 1


@pytest.mark.parametrize(
    "field, value",
    [("domain", True), ("entity_ids", "light.lounge"), ("typo", "unexpected")],
)
def test_service_call_rejects_invalid_fields(field, value):
    with pytest.raises(ValidationError):
        ServiceCall.model_validate(
            {
                "domain": "light",
                "service": "turn_on",
                "entity_ids": ("light.lounge",),
                field: value,
            }
        )
