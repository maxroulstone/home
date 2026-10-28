"""Validated outgoing Home Assistant service requests."""

from pydantic import ConfigDict, Field

from .base import HAModel, JSONValue


class ServiceCall(HAModel):
    """A request to HA; sending it does not confirm the resulting device state."""

    # These fields come from our code, so unexpected fields indicate a mistake.
    model_config = ConfigDict(extra="forbid")

    domain: str
    service: str
    entity_ids: tuple[str, ...]
    data: dict[str, JSONValue] = Field(default_factory=dict)
