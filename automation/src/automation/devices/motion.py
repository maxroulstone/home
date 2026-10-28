"""Reported movement, without assuming the sensor reports when motion stops."""

from pydantic import AwareDatetime

from automation.models.base import State


class MotionState(State):
    """Latest known movement report and sensor availability.

    None means no movement report is known, not that the room is unoccupied.
    Availability changes may retain last_motion_at; they aren't new movement.
    Occupancy modes and expiry deadlines belong to automation rules, not sensors.
    """

    available: bool
    last_motion_at: AwareDatetime | None = None
