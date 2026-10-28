"""Person presence observations, independent of tracker integrations."""

from typing import Literal

from pydantic import Field

from automation.models.base import State


class PersonState(State):
    """One person's reported presence, identified by a logical person ID.

    person_id is our identifier. Adapters map
    backend locations into home/away; a named location outside home is away.
    Unknown/unavailable presence must not be counted as a confirmed absence.
    Household counts are derived from observations for distinct people; they
    aren't part of an individual person's state.
    """

    person_id: str = Field(min_length=1)
    presence: Literal["home", "away", "unknown", "unavailable"]

    @property
    def is_home(self) -> bool | None:
        """Return None when presence is unknown, rather than assuming away."""
        if self.presence in ("unknown", "unavailable"):
            return None
        return self.presence == "home"

    @property
    def available(self) -> bool:
        """Unknown presence is distinct from an explicitly unavailable source."""
        return self.presence != "unavailable"
