"""The light commands automation rules can request from any backend."""

from typing import Annotated, Literal, Protocol

from pydantic import Field

from automation.models.base import State


type BrightnessPercent = Annotated[int, Field(strict=True, ge=0, le=100)]
type ColorTemperatureKelvin = Annotated[int, Field(strict=True, gt=0)]
type RGBChannel = Annotated[int, Field(strict=True, ge=0, le=255)]
type RGBColor = Annotated[tuple[RGBChannel, RGBChannel, RGBChannel], Field(strict=True)]


class LightState(State):
    """A reported observation, independent of requested actions and integrations.

    updated_at is the source's last update time, not when we fetched a snapshot.
    Optional attributes may be absent or last-known while off/unavailable; check
    power before using them. Assumed observations aren't independent confirmation
    from a physical device. Both colour attributes may be reported together.
    """

    power: Literal["on", "off", "unknown", "unavailable"]
    brightness_pct: (
        Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None
    ) = None
    color_temp_kelvin: ColorTemperatureKelvin | None = None
    rgb_color: RGBColor | None = None
    assumed: bool = False

    @property
    def is_on(self) -> bool | None:
        """Unknown and unavailable must not be treated as off."""
        if self.power in ("unknown", "unavailable"):
            return None
        return self.power == "on"

    @property
    def available(self) -> bool:
        """Whether the source reports the light as available, even if state is unknown."""
        return self.power != "unavailable"


class LightCommandError(Exception):
    """A light command could not be confirmed; it may already have taken effect."""


class Light(Protocol):
    """Request light actions without depending on a particular integration.

    Successful completion means the request was accepted, not that the light's
    reported state changed. Backend failures raise LightCommandError; invalid
    arguments raise ValueError. Implementations must not replay failed actions.
    Supported colour modes and Kelvin ranges depend on the target device.
    Reported observations are supplied separately as LightState values.
    """

    async def turn_on(
        self,
        *,
        brightness_pct: BrightnessPercent | None = None,
        color_temp_kelvin: ColorTemperatureKelvin | None = None,
        rgb_color: RGBColor | None = None,
    ) -> None:
        """Request on with optional brightness (0-100) and one colour mode.

        Kelvin must be a positive integer; RGB is a tuple of three integers
        from 0-255. RGB and colour temperature cannot be requested together.
        Omitted options are left to the backend's default behaviour.
        """
        ...

    async def turn_off(self) -> None:
        """Request that the light turns off."""
        ...
