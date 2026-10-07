"""Reported entity state and requests to change it."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class EntityState:
    """An entity's state and attributes as reported by Home Assistant.

    Represents a single observation of a home assistant entity. State
    values can include ``unknown`` and ``unavailable``. ``last_changed`` records
    when the state value changed; ``last_updated`` also tracks attribute changes.
    """

    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: datetime
    last_updated: datetime


@dataclass(frozen=True)
class ServiceCall:
    """A request to HA; sending it does not confirm the resulting device state."""

    domain: str
    service: str
    entity_ids: tuple[str, ...]
    data: dict[str, Any] = field(default_factory=dict)
