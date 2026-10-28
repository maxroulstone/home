"""Translate the light interface into Home Assistant service requests."""

from pydantic import ConfigDict, Field, validate_call

from automation.devices.light import (
    BrightnessPercent,
    ColorTemperatureKelvin,
    Light,
    LightCommandError,
    LightState,
    RGBChannel,
    RGBColor,
)

from .client import HAClientError
from .connection import HAConnectionManager
from .models import EntityState, HAModel, JSONValue, ServiceCall, StateChanged


class _LightAttributes(HAModel):
    """Validate the HA attributes we consume; ignore unrelated HA metadata."""

    brightness: int | None = Field(default=None, ge=0, le=255)
    color_temp_kelvin: ColorTemperatureKelvin | None = None
    rgb_color: list[RGBChannel] | None = Field(default=None, min_length=3, max_length=3)
    assumed_state: bool = False


class HALight(Light):
    """One HA light entity or light-group entity, using the shared connection."""

    def __init__(self, manager: HAConnectionManager, *, entity_id: str) -> None:
        self._manager = manager
        self._entity_id = entity_id

    @validate_call(config=ConfigDict(hide_input_in_errors=True))
    async def turn_on(
        self,
        *,
        brightness_pct: BrightnessPercent | None = None,
        color_temp_kelvin: ColorTemperatureKelvin | None = None,
        rgb_color: RGBColor | None = None,
    ) -> None:
        if color_temp_kelvin is not None and rgb_color is not None:
            raise ValueError("Choose either colour temperature or RGB, not both")

        await self._send(
            ServiceCall(
                domain="light",
                service="turn_on",
                entity_ids=(self._entity_id,),
                data=self._build_data_dictionary(
                    brightness_pct=brightness_pct,
                    color_temp_kelvin=color_temp_kelvin,
                    rgb_color=rgb_color,
                ),
            )
        )

    async def turn_off(self) -> None:
        await self._send(
            ServiceCall(
                domain="light", service="turn_off", entity_ids=(self._entity_id,)
            )
        )

    def parse_state(self, state: EntityState) -> LightState:
        """Translate a snapshot entity or event.new_state; do not cache observations.

        Startup/event routing supplies observations for this entity. Repeated
        snapshots preserve the original timestamp, allowing consumers to reconcile
        overlapping or older events. Commands never modify reported observations.
        """
        if state.entity_id != self._entity_id:
            raise ValueError("Observation belongs to a different light")

        attributes = _LightAttributes.model_validate(state.attributes)
        return LightState.model_validate(
            {
                "power": state.state,
                "updated_at": state.last_updated,
                "brightness_pct": (
                    attributes.brightness * 100 / 255
                    if attributes.brightness is not None
                    else None
                ),
                "color_temp_kelvin": attributes.color_temp_kelvin,
                "rgb_color": (
                    tuple(attributes.rgb_color)
                    if attributes.rgb_color is not None
                    else None
                ),
                "assumed": attributes.assumed_state,
            }
        )

    def parse_change(self, change: StateChanged) -> LightState:
        """Translate an event, including removal of the light entity."""
        if change.entity_id != self._entity_id:
            raise ValueError("Observation belongs to a different light")
        if change.new_state is None:
            return LightState(power="unavailable", updated_at=change.time_fired)
        return self.parse_state(change.new_state)

    async def _send(self, call: ServiceCall) -> None:
        try:
            await self._manager.call_service(call)
        except HAClientError:
            # Rules handle device-level errors without importing HA exceptions.
            raise LightCommandError("Light command could not be confirmed") from None

    @staticmethod
    def _build_data_dictionary(
        *,
        brightness_pct: BrightnessPercent | None,
        color_temp_kelvin: ColorTemperatureKelvin | None,
        rgb_color: RGBColor | None,
    ) -> dict[str, JSONValue]:
        """Convert light options to JSON data, omitting unspecified values."""
        values: dict[str, JSONValue] = {
            "brightness_pct": brightness_pct,
            "color_temp_kelvin": color_temp_kelvin,
            "rgb_color": list(rgb_color) if rgb_color is not None else None,
        }
        return {key: value for key, value in values.items() if value is not None}
