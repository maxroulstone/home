"""Robot vacuum commands and reported activity, independent of integrations."""

from typing import Annotated, Literal, Protocol

from pydantic import Field

from automation.models.base import State


class VacuumState(State):
    """Reported activity, battery and location; independent of action requests.

    current_room is a logical room identifier, such as "lounge", not a vendor's
    numeric segment ID or the room we requested. None means the room is unknown;
    the integration adapter is responsible for mapping the reported location.
    """

    activity: Literal[
        "cleaning",
        "paused",
        "returning",
        "docked",
        "idle",
        "error",
        "unknown",
        "unavailable",
    ]
    current_room: Annotated[str, Field(min_length=1)] | None = None
    battery_pct: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = (
        None
    )

    @property
    def available(self) -> bool:
        """Error or unknown activity does not imply an unreachable device."""
        return self.activity != "unavailable"


class VacuumCommandError(Exception):
    """A vacuum request could not be confirmed; it may already have taken effect."""


class Vacuum(Protocol):
    """Commands for a vacuum supporting start, pause and return-to-dock.

    Completion means the request was accepted, not that the activity changed.
    Reported observations arrive separately as VacuumState. Backend failures
    raise VacuumCommandError; implementations must not replay failed actions.
    """

    async def start(self) -> None:
        """Request cleaning starts or resumes."""
        ...

    async def pause(self) -> None:
        """Request cleaning pauses."""
        ...

    async def return_to_dock(self) -> None:
        """Request a return to the charging dock."""
        ...
