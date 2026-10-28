"""Illuminance observations, including when the light level was measured."""

from typing import Annotated, Self

from pydantic import AwareDatetime, Field, model_validator

from automation.models.base import State


class IlluminanceState(State):
    """A lux sample and sensor availability, independent of physical packaging.

    measured_at belongs to the lux sample; updated_at belongs to this observation,
    which can change when availability changes. A movement-triggered sensor's old
    reading must not become fresh just because a new observation was received.
    Missing lux is unknown; zero lux is a valid reading.
    """

    available: bool
    lux: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    measured_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_measurement(self) -> Self:
        if (self.lux is None) != (self.measured_at is None):
            raise ValueError(
                "Lux and its measurement timestamp must be supplied together"
            )
        return self
