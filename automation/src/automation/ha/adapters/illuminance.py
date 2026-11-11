"""Translate HA illuminance observations without inventing fresh lux samples."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, TypeAdapter

from automation.devices.illuminance import IlluminanceState

from ..models import EntityState, HAModel, StateChanged


type LuxReading = Annotated[float, Field(ge=0, allow_inf_nan=False)]
_LUX_READING = TypeAdapter(LuxReading, config=ConfigDict(hide_input_in_errors=True))
_MISSING_READINGS = ("unknown", "unavailable")


class _IlluminanceAttributes(HAModel):
    unit_of_measurement: Literal["lx"] | None = None


class HAIlluminanceSensor:
    """A read-only adapter; previous_state preserves the last known lux sample.

    HA's last_changed is the available evidence for the sample's report time,
    not a hardware measurement timestamp. Without force_update, equal readings
    may be suppressed, so their later measurement times cannot be reconstructed.
    """

    def __init__(self, *, entity_id: str) -> None:
        self._entity_id = entity_id

    @property
    def entity_id(self) -> str:
        return self._entity_id

    def parse_state(
        self,
        state: EntityState,
        *,
        previous_state: IlluminanceState | None = None,
    ) -> IlluminanceState:
        """Translate a snapshot; fetching an old value doesn't make it a new sample."""
        return self._parse_reading(
            state, previous_state=previous_state, is_new_report=False
        )

    def parse_change(
        self,
        change: StateChanged,
        *,
        previous_state: IlluminanceState | None = None,
    ) -> IlluminanceState:
        """Translate a sample or availability change, including entity removal."""
        if change.entity_id != self._entity_id:
            raise ValueError("Observation belongs to a different illuminance sensor")
        old = change.old_state
        if previous_state is None and old is not None:
            previous_state = self.parse_state(old)
        if change.new_state is None:
            return IlluminanceState(
                available=False,
                updated_at=change.time_fired,
                lux=previous_state.lux if previous_state else None,
                measured_at=previous_state.measured_at if previous_state else None,
            )
        is_new_report = (
            old is not None
            and old.state not in _MISSING_READINGS
            and change.new_state.last_changed > old.last_changed
        )
        return self._parse_reading(
            change.new_state,
            previous_state=previous_state,
            is_new_report=is_new_report,
        )

    def _parse_reading(
        self,
        state: EntityState,
        *,
        previous_state: IlluminanceState | None,
        is_new_report: bool,
    ) -> IlluminanceState:
        if state.entity_id != self._entity_id:
            raise ValueError("Observation belongs to a different illuminance sensor")
        if state.state in _MISSING_READINGS:
            return IlluminanceState(
                available=state.state != "unavailable",
                updated_at=state.last_updated,
                lux=previous_state.lux if previous_state else None,
                measured_at=previous_state.measured_at if previous_state else None,
            )
        _IlluminanceAttributes.model_validate(state.attributes)
        lux = _LUX_READING.validate_python(state.state)
        measured_at = state.last_changed
        if (
            previous_state is not None
            and previous_state.lux == lux
            and previous_state.measured_at is not None
        ):
            if not is_new_report or not previous_state.available:
                measured_at = previous_state.measured_at
        return IlluminanceState(
            available=True,
            updated_at=state.last_updated,
            lux=lux,
            measured_at=measured_at,
        )
