"""Reported HA entity states and state-change observations."""

from typing import Self

from pydantic import model_validator

from .base import HAModel, HATimestamp, JSONValue


class EntityState(HAModel):
    """An entity's state and attributes as reported by Home Assistant.

    State values can include ``unknown`` and ``unavailable``. ``last_changed``
    records when the state value changed; ``last_updated`` also tracks attribute
    changes. Both timestamps must include timezone information.
    """

    entity_id: str
    state: str
    attributes: dict[str, JSONValue]
    last_changed: HATimestamp
    last_updated: HATimestamp


class StateChanged(HAModel):
    """An HA state change; creation/removal can have a missing old/new state."""

    entity_id: str
    old_state: EntityState | None
    new_state: EntityState | None
    time_fired: HATimestamp

    @model_validator(mode="after")
    def check_entity_ids(self) -> Self:
        for state in (self.old_state, self.new_state):
            if state is not None and state.entity_id != self.entity_id:
                raise ValueError("State entity IDs must match the changed entity")

        return self
