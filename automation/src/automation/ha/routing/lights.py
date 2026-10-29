"""Route HA observations to registered light-state handlers."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from automation.devices.light import LightState

from ..adapters.light import HALight
from ..models import EntityState, StateChanged


type LightStateHandler = Callable[[LightState | None], Awaitable[None]]


@dataclass
class _LightRegistration:
    """Keep one adapter, recipient and last successfully delivered state together."""

    light: HALight
    on_state_received: LightStateHandler
    latest_state: LightState | None = None


class HALightRouter:
    """Translate registered lights without exposing HA models to their handlers.

    Register once before running the connection manager, then pass handle_state_snapshot
    and handle_state_change to manager.run. The manager awaits these callbacks
    sequentially; the router doesn't create background tasks or own connections.
    Each entity has one handler. Handler exceptions propagate to the caller.
    """

    def __init__(self) -> None:
        self._registrations: dict[str, _LightRegistration] = {}

    def register(self, light: HALight, *, on_state_received: LightStateHandler) -> None:
        """Register the recipient of this light's observations.

        None means a snapshot did not contain the entity. Unlike a removal event,
        this absence has no source update timestamp, so no LightState is invented.
        """
        if light.entity_id in self._registrations:
            raise ValueError("Light entity is already registered")
        self._registrations[light.entity_id] = _LightRegistration(
            light, on_state_received
        )

    async def handle_state_snapshot(self, states: list[EntityState]) -> None:
        """Deliver the authoritative baseline on every connection, even unchanged.

        This resets event comparison for the new session. A missing entity clears
        the previous observation; unrelated entities are ignored.
        """
        entities = {state.entity_id: state for state in states}
        for registration in self._registrations.values():
            entity = entities.get(registration.light.entity_id)
            state = (
                registration.light.parse_state(entity) if entity is not None else None
            )
            await registration.on_state_received(state)
            registration.latest_state = state

    async def handle_state_change(self, change: StateChanged) -> None:
        """Deliver only registered lights with a newer source update timestamp."""
        registration = self._registrations.get(change.entity_id)
        if registration is None:
            return

        state = registration.light.parse_change(change)
        previous = registration.latest_state
        if previous is not None and state.updated_at <= previous.updated_at:
            return

        await registration.on_state_received(state)
        registration.latest_state = state
