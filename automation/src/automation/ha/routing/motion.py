"""Typed motion registration using shared Home Assistant state routing."""

from automation.devices.motion import MotionState

from ..adapters.motion import HAMotionSensor
from .state import HAStateRouter, StateHandler


type MotionStateHandler = StateHandler[MotionState]


class HAMotionRouter(HAStateRouter[MotionState]):
    """Configure sensor translation and preserve history across missing snapshots."""

    def register(
        self,
        sensor: HAMotionSensor,
        *,
        on_state_received: MotionStateHandler,
    ) -> None:
        """Register one recipient before processing snapshots and changes."""
        self._register(
            entity_id=sensor.entity_id,
            parse_state=sensor.parse_state,
            parse_change=sensor.parse_change,
            on_state_received=on_state_received,
            keep_last_known_state_when_entity_absent_from_snapshot=True,
        )
