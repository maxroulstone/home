"""Translate HA binary-sensor observations into reported movement history."""

from typing import Literal

from pydantic import ConfigDict, TypeAdapter

from automation.devices.motion import MotionState

from ..models import EntityState, StateChanged


type BinarySensorStatus = Literal["on", "off", "unknown", "unavailable"]
_BINARY_STATUS = TypeAdapter(
    BinarySensorStatus, config=ConfigDict(hide_input_in_errors=True)
)


class HAMotionSensor:
    """A read-only motion adapter with explicit previous-state input.

    No occupancy timeout or hidden history is maintained here. Snapshots preserve
    known movement history; the first on snapshot can seed the last HA on-report
    time. Repeated movement requires HA to expose a new on report, for example
    using MQTT force_update. Attribute-only updates are not movement.
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
        previous_state: MotionState | None = None,
    ) -> MotionState:
        """Translate a snapshot without rebasing movement time to reconnect time."""
        if state.entity_id != self._entity_id:
            raise ValueError("Observation belongs to a different motion sensor")
        status = _BINARY_STATUS.validate_python(state.state)
        last_motion_at = previous_state.last_motion_at if previous_state else None
        if previous_state is None and status == "on":
            last_motion_at = state.last_changed
        return MotionState(
            available=status != "unavailable",
            updated_at=state.last_updated,
            last_motion_at=last_motion_at,
        )

    def parse_change(
        self,
        change: StateChanged,
        *,
        previous_state: MotionState | None = None,
    ) -> MotionState:
        """Translate a report, retaining motion history across off/unavailable.

        A newer on last_changed distinguishes repeated forced reports from plain
        attribute changes. Recovery from unavailable alone isn't fresh movement.
        """
        if change.entity_id != self._entity_id:
            raise ValueError("Observation belongs to a different motion sensor")
        old = change.old_state
        old_status = (
            _BINARY_STATUS.validate_python(old.state) if old is not None else None
        )
        last_motion_at = previous_state.last_motion_at if previous_state else None
        if previous_state is None and old is not None and old_status == "on":
            last_motion_at = old.last_changed
        if change.new_state is None:
            return MotionState(
                available=False,
                updated_at=change.time_fired,
                last_motion_at=last_motion_at,
            )

        new = change.new_state
        status = _BINARY_STATUS.validate_python(new.state)
        is_movement_report = status == "on" and (
            old_status in (None, "off", "unknown")
            or (
                old is not None
                and old_status == "on"
                and new.last_changed > old.last_changed
            )
        )
        if is_movement_report and (
            last_motion_at is None or new.last_changed > last_motion_at
        ):
            last_motion_at = new.last_changed
        return MotionState(
            available=status != "unavailable",
            updated_at=new.last_updated,
            last_motion_at=last_motion_at,
        )
