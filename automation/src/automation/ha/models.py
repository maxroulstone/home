"""Validated HA observations and requests created by our application."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)


type JSONValue = (
    str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
)


def _parse_timestamp(value: object) -> object:
    # Convert HA's ISO strings while keeping strict validation for other types.
    return datetime.fromisoformat(value) if isinstance(value, str) else value


type HATimestamp = Annotated[AwareDatetime, BeforeValidator(_parse_timestamp)]


class HAModel(BaseModel):
    """Strict, frozen HA data; ignore extras and hide inputs in error text."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


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


class ServiceCall(HAModel):
    """A request to HA; sending it does not confirm the resulting device state."""

    # These fields come from our code, so unexpected fields indicate a mistake.
    model_config = ConfigDict(extra="forbid")

    domain: str
    service: str
    entity_ids: tuple[str, ...]
    data: dict[str, JSONValue] = Field(default_factory=dict)
