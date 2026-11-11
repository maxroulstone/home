"""Validate incoming HA WebSocket messages."""

import json

import pytest
from pydantic import ValidationError

from automation.ha.models.messages import MESSAGE_ADAPTER, CommandResponse


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
