"""Typed illuminance registration using shared Home Assistant state routing."""

from automation.devices.illuminance import IlluminanceState

from ..adapters.illuminance import HAIlluminanceSensor
from .state import HAStateRouter, StateHandler


type IlluminanceStateHandler = StateHandler[IlluminanceState]


class HAIlluminanceRouter(HAStateRouter[IlluminanceState]):
    """Configure sensor translation and preserve history across missing snapshots."""

    def register(
        self,
        sensor: HAIlluminanceSensor,
        *,
        on_state_received: IlluminanceStateHandler,
    ) -> None:
        """Register one recipient before processing snapshots and changes."""
        self._register(
            entity_id=sensor.entity_id,
            parse_state=sensor.parse_state,
            parse_change=sensor.parse_change,
            on_state_received=on_state_received,
            keep_last_known_state_when_entity_absent_from_snapshot=True,
        )
