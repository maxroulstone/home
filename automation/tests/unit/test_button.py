"""Button events describe an actual action and require an aware event time."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from automation.devices.button import ButtonEvent


OCCURRED = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.mark.parametrize("action", ["press", "hold", "release"])
def test_normalised_actions_are_accepted(action):
    event = ButtonEvent(button="brightness_up", action=action, occurred_at=OCCURRED)

    assert event.button == "brightness_up"
    assert event.action == action


@pytest.mark.parametrize(
    "field, value",
    [
        ("button", ""),
        ("action", "toggle"),
        ("occurred_at", datetime(2026, 10, 28)),
    ],
)
def test_invalid_button_events_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ButtonEvent.model_validate(
            {
                "button": "brightness_up",
                "action": "press",
                "occurred_at": OCCURRED,
                field: value,
            }
        )
