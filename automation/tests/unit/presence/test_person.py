"""Person presence preserves uncertainty before household counts are derived."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from automation.presence.person import PersonState


UPDATED = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "presence, is_home, available",
    [
        ("home", True, True),
        ("away", False, True),
        ("unknown", None, True),
        ("unavailable", None, False),
    ],
)
def test_reported_presence_distinguishes_known_location_from_uncertainty(
    presence, is_home, available
):
    state = PersonState(person_id="alex", presence=presence, updated_at=UPDATED)

    assert state.is_home is is_home
    assert state.available is available


@pytest.mark.parametrize(
    "field, value",
    [
        ("person_id", ""),
        ("person_id", 123),
        ("presence", True),
        ("presence", "office"),
        ("updated_at", datetime(2026, 10, 28)),
    ],
)
def test_invalid_person_observations_are_rejected(field, value):
    with pytest.raises(ValidationError):
        PersonState.model_validate(
            {
                "person_id": "alex",
                "presence": "home",
                "updated_at": UPDATED,
                field: value,
            }
        )
