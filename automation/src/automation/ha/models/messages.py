"""HA WebSocket message shapes, validated at the network boundary."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .base import HAModel, HATimestamp, JSONValue
from .state import EntityState


class AuthMessage(HAModel):
    type: Literal["auth_required", "auth_ok", "auth_invalid"]


class CommandResponse(HAModel):
    type: Literal["result"]
    id: int = Field(gt=0)
    success: bool
    result: JSONValue = None


class EventMessage(HAModel):
    type: Literal["event"]
    id: int = Field(gt=0)
    event: dict[str, JSONValue]


type IncomingMessage = Annotated[
    AuthMessage | CommandResponse | EventMessage, Field(discriminator="type")
]

MESSAGE_ADAPTER = TypeAdapter(IncomingMessage)


class StateChangeData(HAModel):
    entity_id: str
    old_state: EntityState | None
    new_state: EntityState | None


class StateChangeEvent(HAModel):
    event_type: Literal["state_changed"]
    data: StateChangeData
    time_fired: HATimestamp
