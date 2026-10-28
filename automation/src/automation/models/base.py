"""Shared validation and state metadata for integration-independent domain models."""

from pydantic import AwareDatetime, BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Strict, frozen domain data; reject unknown fields and hide invalid inputs."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", hide_input_in_errors=True
    )


class State(DomainModel):
    """Shared state metadata with the source's timezone-aware update time.

    Refreshing a snapshot must preserve this time, rather than substituting the
    fetch time. Availability is defined by each specific state model.
    """

    updated_at: AwareDatetime
