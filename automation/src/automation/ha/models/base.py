"""Shared validation, JSON values and timestamps for HA API data."""

from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict


type JSONValue = (
    str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
)


def _parse_timestamp(value: object) -> object:
    # Convert HA's ISO strings while keeping strict validation for other types.
    return datetime.fromisoformat(value) if isinstance(value, str) else value


type HATimestamp = Annotated[AwareDatetime, BeforeValidator(_parse_timestamp)]


class HAModel(BaseModel):
    """Strict, frozen HA data; ignore extras and hide inputs in error text."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )
