"""Shared state routing, delivery and source-timestamp filtering for HA entities."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from automation.models.base import State

from ..models import EntityState, StateChanged


type StateHandler[StateType: State] = Callable[[StateType | None], Awaitable[None]]


class SnapshotStateParser[StateType: State](Protocol):
    """Translate a snapshot with previous state supplied by name."""

    def __call__(
        self, state: EntityState, *, previous_state: StateType | None
    ) -> StateType: ...


class StateChangeParser[StateType: State](Protocol):
    """Translate a change with previous state supplied by name."""

    def __call__(
        self, change: StateChanged, *, previous_state: StateType | None
    ) -> StateType: ...


@dataclass
class _StateRegistration[StateType: State]:
    parse_state: SnapshotStateParser[StateType]
    parse_change: StateChangeParser[StateType]
    on_state_received: StateHandler[StateType]
    keep_last_known_state_when_entity_absent_from_snapshot: bool
    last_known_state: StateType | None = None
    latest_update_at: datetime | None = None


class HAStateRouter[StateType: State]:
    """Route one domain-state type using supplied translation functions.

    Light and sensor routers inherit this behaviour and specialise registration.
    Snapshots establish the session baseline and are always delivered. Events must
    be newer than that baseline.
    Callbacks run sequentially; history is advanced only after delivery succeeds.
    """

    def __init__(self) -> None:
        self._registrations: dict[str, _StateRegistration[StateType]] = {}

    def _register(
        self,
        *,
        entity_id: str,
        parse_state: SnapshotStateParser[StateType],
        parse_change: StateChangeParser[StateType],
        on_state_received: StateHandler[StateType],
        keep_last_known_state_when_entity_absent_from_snapshot: bool = False,
    ) -> None:
        """Configure one entity for a subclass's public registration method."""
        if entity_id in self._registrations:
            raise ValueError("HA entity is already registered")
        self._registrations[entity_id] = _StateRegistration(
            parse_state=parse_state,
            parse_change=parse_change,
            on_state_received=on_state_received,
            keep_last_known_state_when_entity_absent_from_snapshot=keep_last_known_state_when_entity_absent_from_snapshot,
        )

    async def handle_state_snapshot(self, states: list[EntityState]) -> None:
        """Deliver baselines, using None for missing entities without inventing time."""
        entities = {state.entity_id: state for state in states}
        for entity_id, registration in self._registrations.items():
            entity = entities.get(entity_id)
            state = (
                registration.parse_state(
                    entity, previous_state=registration.last_known_state
                )
                if entity is not None
                else None
            )
            await self._call_registered_state_handler(registration, state)

    async def handle_state_change(self, change: StateChanged) -> None:
        """Reject unrelated or stale events before invoking their parser."""
        registration = self._registrations.get(change.entity_id)
        if registration is None:
            return
        updated_at = (
            change.new_state.last_updated
            if change.new_state is not None
            else change.time_fired
        )
        if (
            registration.latest_update_at is not None
            and updated_at <= registration.latest_update_at
        ):
            return

        state = registration.parse_change(
            change, previous_state=registration.last_known_state
        )
        await self._call_registered_state_handler(registration, state)

    async def _call_registered_state_handler(
        self,
        registration: _StateRegistration[StateType],
        state: StateType | None,
    ) -> None:
        await registration.on_state_received(state)
        if (
            state is not None
            or not registration.keep_last_known_state_when_entity_absent_from_snapshot
        ):
            registration.last_known_state = state
        registration.latest_update_at = state.updated_at if state is not None else None
