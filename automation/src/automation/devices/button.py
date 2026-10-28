"""Button actions are discrete events, not persistent on/off device states."""

from typing import Literal

from pydantic import AwareDatetime, Field

from automation.models.base import DomainModel


class ButtonEvent(DomainModel):
    """One normalised action from a control on a remote.

    button is a logical control name, independent of integration identifiers.
    Each occurrence must be delivered, including consecutive identical actions.
    Adapters map only actions the actual remote reports; they must not invent a
    release or hold event. Additional action types can be added when needed.
    """

    button: str = Field(min_length=1)
    action: Literal["press", "hold", "release"]
    occurred_at: AwareDatetime
