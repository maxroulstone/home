"""Typed light registration using shared Home Assistant state routing."""

from automation.devices.light import LightState

from ..adapters.light import HALight
from .state import HAStateRouter, StateHandler


type LightStateHandler = StateHandler[LightState]


class HALightRouter(HAStateRouter[LightState]):
    """Configure light translation; shared delivery lives in HAStateRouter."""

    def register(
        self,
        light: HALight,
        *,
        on_state_received: LightStateHandler,
    ) -> None:
        """Register one recipient before processing snapshots and changes."""
        self._register(
            entity_id=light.entity_id,
            parse_state=light.parse_state,
            parse_change=light.parse_change,
            on_state_received=on_state_received,
        )
